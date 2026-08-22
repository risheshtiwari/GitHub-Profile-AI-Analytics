"""Repo Chat — Stage 5: orchestration.

Two flows live here.

**Indexing** (`index_repository`): url -> metadata + snapshot -> chunks ->
embeddings -> Postgres. Status is tracked on the `IndexedRepo` row so the API
can run it as a background job and report progress.

**Answering** (`answer_question`): the part that makes follow-up questions work.

    1. *Condense* — a follow-up like "why?" or "and where is that called from?"
       is meaningless to a retriever. The last few turns plus the new question
       are rewritten into one standalone query before retrieval. This is the
       single biggest quality lever for multi-turn RAG.
    2. *Retrieve* — hybrid search + MMR over the repo's chunks.
    3. *Ground* — chunks are numbered and injected with their file paths and
       line ranges; the model is instructed to cite `[n]` and to say when the
       context doesn't cover the question rather than inventing an answer.
    4. *Answer* — with a repo card (tree, languages, manifests) always present,
       so structural questions like "what does this project do?" work even when
       retrieval misses.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession, IndexedRepo, RepoChunk
from app.services import chunker, repo_ingest, vector_store
from app.services.embeddings import get_embedder, tokenize
from app.services.github_client import GitHubClient
from app.services.repo_ingest import RepoRef

logger = logging.getLogger(__name__)
settings = get_settings()


class RepoNotIndexedError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


# --------------------------------------------------------------------------- #
# In-process retrieval cache
# --------------------------------------------------------------------------- #
# Chunk rows + embedding matrix for a repo, keyed by (repo_id, indexed_at).
# Reloading a few thousand JSON vectors from Postgres on every message would
# dominate response latency; the indexed_at stamp invalidates on re-index.
_MATRIX_CACHE: dict[tuple[int, str], tuple[list[dict], list[list[float]], list[list[str]]]] = {}
_MATRIX_CACHE_LIMIT = 8


async def _load_repo_index(db: AsyncSession, repo: IndexedRepo):
    key = (repo.id, str(repo.indexed_at))
    cached = _MATRIX_CACHE.get(key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(RepoChunk).where(RepoChunk.repo_id == repo.id).order_by(RepoChunk.ordinal)
    )
    rows = result.scalars().all()

    chunks = [
        {
            "id": row.id,
            "path": row.path,
            "language": row.language,
            "symbol": row.symbol,
            "start_line": row.start_line,
            "end_line": row.end_line,
            "content": row.content,
        }
        for row in rows
    ]
    matrix = [row.embedding or [] for row in rows]
    token_docs = [
        tokenize(f"{row.path} {row.symbol or ''}\n{row.content}") for row in rows
    ]

    if len(_MATRIX_CACHE) >= _MATRIX_CACHE_LIMIT:
        _MATRIX_CACHE.pop(next(iter(_MATRIX_CACHE)))
    _MATRIX_CACHE[key] = (chunks, matrix, token_docs)
    return chunks, matrix, token_docs


def invalidate_repo_cache(repo_id: int) -> None:
    for key in [k for k in _MATRIX_CACHE if k[0] == repo_id]:
        _MATRIX_CACHE.pop(key, None)


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #


async def get_or_create_repo_row(db: AsyncSession, ref: RepoRef) -> IndexedRepo:
    result = await db.execute(select(IndexedRepo).where(IndexedRepo.full_name == ref.full_name))
    repo = result.scalar_one_or_none()
    if repo is None:
        repo = IndexedRepo(
            owner=ref.owner, repo=ref.repo, full_name=ref.full_name, ref=ref.ref, status="pending"
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
    return repo


async def index_repository(db: AsyncSession, ref: RepoRef, force: bool = False) -> IndexedRepo:
    """Full ingest -> chunk -> embed -> persist. Idempotent unless `force`."""
    repo = await get_or_create_repo_row(db, ref)

    if repo.status == "ready" and not force:
        return repo

    repo.status = "indexing"
    repo.error = None
    await db.commit()

    client = GitHubClient()
    try:
        metadata, snapshot = await repo_ingest.fetch_repo_snapshot(ref, client=client)
        languages = await client.get_repo_languages(ref.owner, ref.repo)

        chunks, coverage = chunker.chunk_files(snapshot.files)
        if not chunks:
            raise repo_ingest.EmptyRepoError(ref.full_name)

        embedder = get_embedder()
        vectors = await embedder.embed_documents([chunk.embedding_text() for chunk in chunks])

        # Replace the previous index wholesale — simpler and safer than diffing.
        await db.execute(delete(RepoChunk).where(RepoChunk.repo_id == repo.id))
        for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors)):
            db.add(
                RepoChunk(
                    repo_id=repo.id,
                    ordinal=ordinal,
                    path=chunk.path,
                    language=chunk.language,
                    symbol=chunk.symbol,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    token_estimate=chunk.token_estimate,
                    embedding=vector,
                )
            )

        repo.default_branch = metadata.get("default_branch")
        repo.ref = snapshot.ref.ref or metadata.get("default_branch")
        repo.description = (metadata.get("description") or "")[:1000] or None
        repo.homepage = (metadata.get("homepage") or "")[:500] or None
        repo.primary_language = metadata.get("language")
        repo.languages = languages
        repo.topics = metadata.get("topics") or []
        repo.stars = metadata.get("stargazers_count", 0)
        repo.forks = metadata.get("forks_count", 0)
        repo.file_tree = snapshot.file_tree
        repo.readme_excerpt = snapshot.readme_excerpt or None
        repo.manifest_summary = snapshot.manifest_summary
        repo.coverage = coverage
        repo.file_count = len(snapshot.files)
        repo.chunk_count = len(chunks)
        repo.total_bytes = snapshot.total_bytes
        repo.embedding_model = embedder.name
        repo.embedding_dim = embedder.dimensions
        repo.indexed_at = datetime.utcnow()
        repo.status = "ready"

        await db.commit()
        await db.refresh(repo)
        invalidate_repo_cache(repo.id)
        if coverage["budget_reached"]:
            logger.warning(
                "Chunk budget (%d) reached for %s: %d file(s) not indexed, %d partially indexed. "
                "Answers cannot cite those files. Raise INGEST_MAX_CHUNKS for full coverage.",
                coverage["chunk_budget"], ref.full_name,
                len(coverage["files_not_indexed"]), len(coverage["files_partially_indexed"]),
            )
        logger.info("Indexed %s: %d files, %d chunks", ref.full_name, repo.file_count, repo.chunk_count)
        return repo
    except Exception as exc:  # noqa: BLE001 — surface the failure on the row
        await db.rollback()
        repo.status = "failed"
        repo.error = f"{type(exc).__name__}: {exc}"[:1000]
        await db.commit()
        logger.exception("Indexing failed for %s", ref.full_name)
        raise
    finally:
        await client.close()


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


def build_repo_card(repo: IndexedRepo, tree_limit: int = 60) -> str:
    """Always-present structural context: what the project is, how it's laid
    out, what it depends on. Cheap, and it answers a whole class of questions
    retrieval alone would fumble."""
    languages = repo.languages or {}
    total = sum(languages.values()) or 1
    language_line = ", ".join(
        f"{name} {round(100 * size / total)}%"
        for name, size in sorted(languages.items(), key=lambda item: -item[1])[:6]
    )
    tree = "\n".join((repo.file_tree or [])[:tree_limit])
    manifests = "\n".join(
        f"--- {path} ---\n{content[:600]}"
        for path, content in list((repo.manifest_summary or {}).items())[:4]
    )

    parts = [
        f"REPOSITORY: {repo.full_name} (branch: {repo.ref or repo.default_branch})",
        f"DESCRIPTION: {repo.description or 'n/a'}",
        f"TOPICS: {', '.join(repo.topics or []) or 'n/a'}",
        f"LANGUAGES: {language_line or 'n/a'}",
        f"STARS: {repo.stars} | FORKS: {repo.forks} | INDEXED FILES: {repo.file_count}",
        f"\nFILE TREE (truncated):\n{tree}",
    ]
    if repo.readme_excerpt:
        parts.append(f"\nREADME (excerpt):\n{repo.readme_excerpt[:2000]}")
    if manifests:
        parts.append(f"\nBUILD / DEPENDENCY MANIFESTS:\n{manifests}")
    return "\n".join(parts)


def build_context_block(selected: list[dict]) -> str:
    blocks = []
    for number, chunk in enumerate(selected, start=1):
        symbol = f" ({chunk['symbol']})" if chunk.get("symbol") else ""
        blocks.append(
            f"[{number}] {chunk['path']}:{chunk['start_line']}-{chunk['end_line']}{symbol}\n"
            f"```{(chunk.get('language') or '').lower()}\n{chunk['content']}\n```"
        )
    return "\n\n".join(blocks)


ANSWER_SYSTEM_PROMPT = (
    "You are a senior engineer who has just read this repository end to end, answering "
    "questions for someone exploring it for the first time.\n\n"
    "Rules:\n"
    "1. Ground every claim in the REPOSITORY OVERVIEW and CODE CONTEXT provided. Do not "
    "invent files, functions, or behaviour that are not shown.\n"
    "2. Cite the code you rely on with bracketed numbers matching the context blocks, "
    "e.g. [2]. Cite at the end of the sentence the claim is in.\n"
    "3. Explain *how* something works, not just what it is: name the functions involved, "
    "the order they run in, and the data that flows between them.\n"
    "4. If the context is insufficient, say exactly what is missing and which file or "
    "directory would likely hold the answer. Never guess silently.\n"
    "5. Be concise and concrete. Short code excerpts are welcome; long dumps are not.\n"
    "6. Distinguish what the code does from what the README claims it does, if they differ."
)

CONDENSE_SYSTEM_PROMPT = (
    "Rewrite the user's latest message into a single standalone search query for a code "
    "search engine, resolving all pronouns and references using the conversation history. "
    "Keep concrete identifiers (file names, function names, classes) verbatim. "
    "If the message is already standalone, return it unchanged. "
    'Respond ONLY with JSON: {"query": "..."}.'
)


# --------------------------------------------------------------------------- #
# Answering
# --------------------------------------------------------------------------- #


def _get_llm():
    from app.services.ai_engine import get_client

    return get_client()


async def condense_question(history: list[dict], question: str) -> str:
    """Turns a context-dependent follow-up into a standalone retrieval query."""
    if not history:
        return question
    try:
        client = _get_llm()
        transcript = "\n".join(f"{msg['role']}: {msg['content'][:500]}" for msg in history[-6:])
        response = await client.chat.completions.create(
            model=settings.chat_model,
            messages=[
                {"role": "system", "content": CONDENSE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Conversation:\n{transcript}\n\nLatest message: {question}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        rewritten = json.loads(response.choices[0].message.content).get("query")
        return rewritten.strip() if rewritten else question
    except Exception:  # noqa: BLE001 — condensing is an optimisation, not a requirement
        logger.warning("Question condensing failed; falling back to raw question", exc_info=True)
        return question


async def retrieve(db: AsyncSession, repo: IndexedRepo, query: str, top_k: int | None = None) -> list[dict]:
    chunks, matrix, token_docs = await _load_repo_index(db, repo)
    if not chunks:
        return []

    embedder = get_embedder()
    query_vector = await embedder.embed_query(query)

    hits = vector_store.search(
        query_vector=query_vector,
        query_text=query,
        matrix=matrix,
        token_docs=token_docs,
        top_k=top_k or settings.retrieval_top_k,
        candidate_k=settings.retrieval_candidate_k,
        vector_weight=settings.retrieval_vector_weight,
    )

    selected = []
    for hit in hits:
        chunk = dict(chunks[hit.index])
        chunk["relevance"] = round(hit.score, 4)
        selected.append(chunk)
    return selected


def _citations_from(selected: list[dict]) -> list[dict]:
    """Citations carry the cited code itself (truncated), so a client can show
    the exact lines an answer rests on without a second round trip."""
    return [
        {
            "n": number,
            "path": chunk["path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "symbol": chunk.get("symbol"),
            "language": chunk.get("language"),
            "content": (chunk.get("content") or "")[:1500],
            "relevance": chunk.get("relevance"),
        }
        for number, chunk in enumerate(selected, start=1)
    ]


def _build_messages(repo: IndexedRepo, history: list[dict], question: str, selected: list[dict]) -> list[dict]:
    messages = [{"role": "system", "content": ANSWER_SYSTEM_PROMPT}]
    messages.append(
        {"role": "system", "content": f"REPOSITORY OVERVIEW\n{build_repo_card(repo)}"}
    )
    for turn in history[-settings.chat_history_turns:]:
        messages.append({"role": turn["role"], "content": turn["content"]})

    context = build_context_block(selected) or "(no matching code found in the index)"
    messages.append(
        {
            "role": "user",
            "content": f"CODE CONTEXT\n{context}\n\nQUESTION\n{question}",
        }
    )
    return messages


async def load_history(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    return [{"role": row.role, "content": row.content} for row in result.scalars().all()]


async def get_session(db: AsyncSession, session_id: str) -> ChatSession:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise SessionNotFoundError(session_id)
    return session


async def create_session(db: AsyncSession, repo: IndexedRepo, user_id: int | None, title: str | None = None) -> ChatSession:
    session = ChatSession(
        id=str(uuid.uuid4()),
        repo_id=repo.id,
        user_id=user_id,
        title=title or f"Chat with {repo.full_name}",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def answer_question(db: AsyncSession, session: ChatSession, question: str, top_k: int | None = None) -> dict:
    started = time.perf_counter()

    result = await db.execute(select(IndexedRepo).where(IndexedRepo.id == session.repo_id))
    repo = result.scalar_one()
    if repo.status != "ready":
        raise RepoNotIndexedError(repo.full_name)

    history = await load_history(db, session.id)
    standalone = await condense_question(history, question)
    selected = await retrieve(db, repo, standalone, top_k=top_k)

    client = _get_llm()
    response = await client.chat.completions.create(
        model=settings.chat_model,
        messages=_build_messages(repo, history, question, selected),
        temperature=0.2,
    )
    answer = response.choices[0].message.content.strip()
    latency_ms = int((time.perf_counter() - started) * 1000)

    citations = _citations_from(selected)
    db.add(ChatMessage(session_id=session.id, role="user", content=question, standalone_question=standalone))
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
            retrieved_paths=sorted({chunk["path"] for chunk in selected}),
            latency_ms=latency_ms,
        )
    )
    session.last_active_at = datetime.utcnow()
    await db.commit()

    return {
        "session_id": session.id,
        "repository": repo.full_name,
        "question": question,
        "standalone_question": standalone,
        "answer": answer,
        "citations": citations,
        "sources": sorted({chunk["path"] for chunk in selected}),
        "latency_ms": latency_ms,
    }


async def stream_answer(db: AsyncSession, session: ChatSession, question: str):
    """Server-sent events: citations first (so the UI can render sources while
    the answer types out), then answer tokens, then a done event."""
    started = time.perf_counter()

    result = await db.execute(select(IndexedRepo).where(IndexedRepo.id == session.repo_id))
    repo = result.scalar_one()
    if repo.status != "ready":
        raise RepoNotIndexedError(repo.full_name)

    history = await load_history(db, session.id)
    standalone = await condense_question(history, question)
    selected = await retrieve(db, repo, standalone)
    citations = _citations_from(selected)

    yield f"event: citations\ndata: {json.dumps(citations)}\n\n"

    client = _get_llm()
    stream = await client.chat.completions.create(
        model=settings.chat_model,
        messages=_build_messages(repo, history, question, selected),
        temperature=0.2,
        stream=True,
    )

    collected: list[str] = []
    async for part in stream:
        if not part.choices:
            continue
        token = part.choices[0].delta.content
        if token:
            collected.append(token)
            yield f"event: token\ndata: {json.dumps({'t': token})}\n\n"

    answer = "".join(collected).strip()
    latency_ms = int((time.perf_counter() - started) * 1000)

    db.add(ChatMessage(session_id=session.id, role="user", content=question, standalone_question=standalone))
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
            retrieved_paths=sorted({chunk["path"] for chunk in selected}),
            latency_ms=latency_ms,
        )
    )
    session.last_active_at = datetime.utcnow()
    await db.commit()

    yield f"event: done\ndata: {json.dumps({'latency_ms': latency_ms, 'session_id': session.id})}\n\n"


# --------------------------------------------------------------------------- #
# Repo overview (one-shot architectural summary)
# --------------------------------------------------------------------------- #

OVERVIEW_SYSTEM_PROMPT = (
    "You are a staff engineer writing an onboarding brief for a repository you have just read. "
    "Respond ONLY with a JSON object with these keys: "
    '"what_it_does" (2-3 sentence plain-English summary), '
    '"how_it_works" (array of 3-6 strings, each describing one step or component in the '
    'runtime flow), "architecture" (array of {"component": str, "responsibility": str, "path": str}), '
    '"tech_stack" (array of short strings), "entry_points" (array of file paths a newcomer should '
    'read first), "notable_patterns" (array of short strings), '
    '"suggested_questions" (array of 5 specific questions a newcomer could usefully ask about '
    "this codebase). Ground everything in the provided material."
)


async def generate_overview(db: AsyncSession, repo: IndexedRepo) -> dict:
    """A structured 'what is this and how does it work' brief — the natural
    landing view before the user starts asking their own questions."""
    if repo.status != "ready":
        raise RepoNotIndexedError(repo.full_name)

    # Seed with entry-point-ish chunks so the model sees real wiring code.
    selected = await retrieve(
        db, repo, "application entry point main setup architecture routes configuration", top_k=10
    )

    client = _get_llm()
    response = await client.chat.completions.create(
        model=settings.chat_model,
        messages=[
            {"role": "system", "content": OVERVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"REPOSITORY OVERVIEW\n{build_repo_card(repo, tree_limit=100)}\n\n"
                    f"KEY CODE\n{build_context_block(selected)}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(response.choices[0].message.content)
