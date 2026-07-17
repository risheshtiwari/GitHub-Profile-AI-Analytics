from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import AIAnalysis, User
from app.db.session import get_db
from app.schemas.developer import AnalyzeRequest, DeveloperOut
from app.services import ai_engine
from app.services.pipeline import DeveloperNotFoundError, collect_and_analyze, persist_analysis

router = APIRouter(tags=["analyze"])


@router.post("/analyze", response_model=DeveloperOut)
async def analyze_developer(
    payload: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Runs the full pipeline: collect GitHub data, compute analytics, persist,
    then kick off AI-generated insights (stored for the GET /summary, /interview
    endpoints to read back)."""
    try:
        analysis = await collect_and_analyze(payload.username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail=f"GitHub user '{payload.username}' not found")

    developer = await persist_analysis(db, analysis)

    # AI phase — best-effort; deterministic analytics above already succeeded and are saved.
    try:
        skill_analysis = await ai_engine.generate_skill_analysis(
            analysis["profile"], analysis["repositories"], analysis["languages"], analysis["activity"]
        )
        summary = await ai_engine.generate_resume_summary(analysis["profile"], skill_analysis)
        questions = await ai_engine.generate_interview_questions(
            analysis["profile"], analysis["languages"], skill_analysis
        )

        existing = (await db.execute(select(AIAnalysis).where(AIAnalysis.developer_id == developer.id))).scalar_one_or_none()
        if existing is None:
            existing = AIAnalysis(developer_id=developer.id)
            db.add(existing)
        existing.summary = summary
        existing.strengths = skill_analysis.get("strengths")
        existing.weaknesses = skill_analysis.get("weaknesses")
        existing.likely_expertise = skill_analysis.get("likely_expertise")
        existing.suggested_learning = skill_analysis.get("suggested_learning")
        existing.interview_questions = questions
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        # Don't fail the whole request if the AI provider errors out — the
        # deterministic analytics are already saved and useful on their own.
        import logging
        logging.getLogger(__name__).warning("AI analysis failed for %s: %s", payload.username, exc)

    await db.refresh(developer)
    return developer
