from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import ActivityOut
from app.services import activity_analyzer
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["activity"])


@router.get("/activity/{username}", response_model=ActivityOut)
async def get_activity(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")

    # Rebuild a merged-week structure from stored CommitHistory rows
    merged = {
        int(ch.week_start.timestamp()): {"total": ch.count, "days": [0] * 7}
        for ch in developer.commit_history
    }
    return ActivityOut(
        commits_per_week=activity_analyzer.commits_per_week_series(merged),
        commits_per_month=activity_analyzer.commits_per_month(merged),
        longest_streak_weeks=activity_analyzer.longest_streak_weeks(merged),
        most_active_weekday=None,  # per-weekday breakdown isn't persisted; see /analyze response for full detail
        average_commits_per_week=activity_analyzer.average_commits_per_week(merged),
        inactive_periods=activity_analyzer.inactive_periods(merged),
    )
