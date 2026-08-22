from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import LanguageStatsOut
from app.services import language_analyzer
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["languages"])


@router.get("/languages/{username}", response_model=LanguageStatsOut)
async def get_languages(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")

    totals = language_analyzer.aggregate_languages([r.languages or {} for r in developer.repositories])
    return LanguageStatsOut(
        distribution_percent=language_analyzer.language_distribution_percent(totals),
        primary_language=max(totals, key=totals.get) if totals else None,
        language_diversity_score=language_analyzer.language_diversity_score(totals),
        backend_frontend_ratio=language_analyzer.backend_frontend_ratio(totals),
        ai_ml_ecosystem_detected=language_analyzer.detect_ai_ml_ecosystem(
            [r.topics or [] for r in developer.repositories],
            [r.primary_language for r in developer.repositories],
        ),
    )
