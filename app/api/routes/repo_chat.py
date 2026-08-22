"""Repo Chat endpoints — point at a GitHub repo URL and ask it questions.

    POST   /repo-chat/index                        index a repository (background by default)
    GET    /repo-chat/repos                        list indexed repositories
    GET    /repo-chat/repos/{owner}/{repo}         index status / stats
    DELETE /repo-chat/repos/{owner}/{repo}         drop an index
    GET    /repo-chat/repos/{owner}/{repo}/overview  AI "what & how" brief
    POST   /repo-chat/sessions                     open a conversation
    GET    /repo-chat/sessions                     list your conversations
    GET    /repo-chat/sessions/{id}/messages       transcript
    POST   /repo-chat/sessions/{id}/messages       ask (multi-turn, follow-ups work)
    POST   /repo-chat/sessions/{id}/messages/stream  same, streamed over SSE
    DELETE /repo-chat/sessions/{id}                delete a conversation
    POST   /repo-chat/ask                          one-shot: index + session + ask
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import ChatMessage, ChatSession, IndexedRepo, User
from app.db.session import AsyncSessionLocal, get_db
from app.schemas.repo_chat import (
    AskRequest,
    ChatAnswerOut,
    ChatRequest,
    IndexRequest,
    IndexStatusOut,
    MessageOut,
    RepoOverviewOut,
    SessionCreateRequest,
    SessionOut,
)
from app.services import repo_chat
from app.services.cache import cache_get, cache_set
from app.services.repo_ingest import (
    EmptyRepoError,
    InvalidRepoUrlError,
    RepoNotFoundError,
    RepoRef,
    parse_repo_url,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repo-chat", tags=["repo-chat"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_or_400(repo_url: str, ref: str | None = None) -> RepoRef:
    try:
        parsed = parse_repo_url(repo_url)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RepoRef(parsed.owner, parsed.repo, ref or parsed.ref)


async def _index_in_background(ref: RepoRef, force: bool) -> None:
    """Background jobs get their own session — the request's session is closed
    by the time this runs."""
    async with AsyncSessionLocal() as db:
        try:
            await repo_chat.index_repository(db, ref, force=force)
        except Exception:  # noqa: BLE001 — status/error already persisted on the row
            logger.exception("Background indexing failed for %s", ref.full_name)


async def _get_repo_or_404(db: AsyncSession, full_name: str) -> IndexedRepo:
    result = await db.execute(select(IndexedRepo).where(IndexedRepo.full_name == full_name))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{full_name}' has not been indexed. Call POST /repo-chat/index first.",
        )
    return repo


async def _ensure_indexed(db: AsyncSession, ref: RepoRef) -> IndexedRepo:
    """Index on demand, mapping ingestion failures onto sensible HTTP codes."""
    try:
        return await repo_chat.index_repository(db, ref)
    except RepoNotFoundError:
        raise HTTPException(status_code=404, detail=f"Repository '{ref.full_name}' not found or is private")
    except EmptyRepoError:
        raise HTTPException(status_code=422, detail=f"No ingestible source files found in '{ref.full_name}'")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Indexing failed: {type(exc).__name__}: {exc}")


async def _owned_session_or_404(db: AsyncSession, session_id: str, user: User) -> ChatSession:
    try:
        session = await repo_chat.get_session(db, session_id)
    except repo_chat.SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id is not None and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="This chat session belongs to another user")
    return session


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #


@router.post("/index", response_model=IndexStatusOut, status_code=202)
async def index_repo(
    payload: IndexRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ingest a repository so it can be chatted with.

    Returns immediately with `status: "pending"` and indexes in the background;
    poll `GET /repo-chat/repos/{owner}/{repo}`. Pass `wait: true` to block until
    the index is ready (handy from curl, slow for big repos).
    """
    ref = _parse_or_400(payload.repo_url, payload.ref)

    if payload.wait:
        if payload.force:
            return await _force_index(db, ref)
        return await _ensure_indexed(db, ref)

    repo = await repo_chat.get_or_create_repo_row(db, ref)
    if repo.status == "ready" and not payload.force:
        return repo

    repo.status = "pending"
    await db.commit()
    background_tasks.add_task(_index_in_background, ref, payload.force)
    await db.refresh(repo)
    return repo


async def _force_index(db: AsyncSession, ref: RepoRef) -> IndexedRepo:
    try:
        return await repo_chat.index_repository(db, ref, force=True)
    except RepoNotFoundError:
        raise HTTPException(status_code=404, detail=f"Repository '{ref.full_name}' not found or is private")
    except EmptyRepoError:
        raise HTTPException(status_code=422, detail=f"No ingestible source files found in '{ref.full_name}'")


@router.get("/repos", response_model=list[IndexStatusOut])
async def list_indexed_repos(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IndexedRepo).order_by(IndexedRepo.updated_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/repos/{owner}/{repo}", response_model=IndexStatusOut)
async def get_index_status(owner: str, repo: str, db: AsyncSession = Depends(get_db)):
    return await _get_repo_or_404(db, f"{owner}/{repo}")


@router.delete("/repos/{owner}/{repo}", status_code=204)
async def delete_index(
    owner: str,
    repo: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_repo_or_404(db, f"{owner}/{repo}")
    repo_chat.invalidate_repo_cache(row.id)
    await db.delete(row)
    await db.commit()


@router.get("/repos/{owner}/{repo}/overview", response_model=RepoOverviewOut)
async def repo_overview(owner: str, repo: str, db: AsyncSession = Depends(get_db)):
    """Structured 'what does this repo do and how' brief, plus suggested
    starting questions. Cached in Redis — it's a fixed-cost LLM call per repo."""
    full_name = f"{owner}/{repo}"
    row = await _get_repo_or_404(db, full_name)
    if row.status != "ready":
        raise HTTPException(status_code=409, detail=f"Index status is '{row.status}', not ready")

    cache_key = f"repo_overview:{full_name}:{row.indexed_at}"
    try:
        cached = await cache_get(cache_key)
    except Exception:  # noqa: BLE001 — Redis being down shouldn't break the endpoint
        cached = None
    if cached:
        return RepoOverviewOut(repository=full_name, **cached)

    try:
        overview = await repo_chat.generate_overview(db, row)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Overview generation failed: {exc}")

    try:
        await cache_set(cache_key, overview)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to cache repo overview for %s", full_name)
    return RepoOverviewOut(repository=full_name, **overview)


# --------------------------------------------------------------------------- #
# Sessions & chat
# --------------------------------------------------------------------------- #


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    payload: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Opens a conversation against a repo, indexing it first if needed."""
    ref = _parse_or_400(payload.repo_url, payload.ref)
    repo = await _ensure_indexed(db, ref)
    session = await repo_chat.create_session(db, repo, current_user.id, payload.title)
    return SessionOut(
        id=session.id,
        repository=repo.full_name,
        title=session.title,
        message_count=0,
        created_at=session.created_at,
        last_active_at=session.last_active_at,
    )


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession, IndexedRepo.full_name, func.count(ChatMessage.id))
        .join(IndexedRepo, IndexedRepo.id == ChatSession.repo_id)
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == current_user.id)
        .group_by(ChatSession.id, IndexedRepo.full_name)
        .order_by(ChatSession.last_active_at.desc())
    )
    return [
        SessionOut(
            id=session.id,
            repository=full_name,
            title=session.title,
            message_count=count,
            created_at=session.created_at,
            last_active_at=session.last_active_at,
        )
        for session, full_name, count in result.all()
    ]


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_transcript(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_session_or_404(db, session_id, current_user)
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    return result.scalars().all()


@router.post("/sessions/{session_id}/messages", response_model=ChatAnswerOut)
async def send_message(
    session_id: str,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question. Prior turns in this session are used to resolve
    follow-ups ("why is that?", "where is it called from?") before retrieval."""
    session = await _owned_session_or_404(db, session_id, current_user)
    try:
        return await repo_chat.answer_question(db, session, payload.question, payload.top_k)
    except repo_chat.RepoNotIndexedError as exc:
        raise HTTPException(status_code=409, detail=f"Repository '{exc}' is not ready yet")


@router.post("/sessions/{session_id}/messages/stream")
async def send_message_stream(
    session_id: str,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Same as above, streamed as SSE: a `citations` event, then `token`
    events, then `done`."""
    session = await _owned_session_or_404(db, session_id, current_user)
    try:
        generator = repo_chat.stream_answer(db, session, payload.question)
    except repo_chat.RepoNotIndexedError as exc:
        raise HTTPException(status_code=409, detail=f"Repository '{exc}' is not ready yet")
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _owned_session_or_404(db, session_id, current_user)
    await db.delete(session)
    await db.commit()


@router.post("/ask", response_model=ChatAnswerOut)
async def ask(
    payload: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One-shot entry point: give a repo URL and a question. Indexes the repo if
    it's new, reuses `session_id` if supplied so follow-ups keep their context."""
    ref = _parse_or_400(payload.repo_url, payload.ref)
    repo = await _ensure_indexed(db, ref)

    if payload.session_id:
        session = await _owned_session_or_404(db, payload.session_id, current_user)
        if session.repo_id != repo.id:
            raise HTTPException(status_code=400, detail="That session belongs to a different repository")
    else:
        session = await repo_chat.create_session(db, repo, current_user.id, payload.question[:120])

    try:
        return await repo_chat.answer_question(db, session, payload.question)
    except repo_chat.RepoNotIndexedError as exc:
        raise HTTPException(status_code=409, detail=f"Repository '{exc}' is not ready yet")
