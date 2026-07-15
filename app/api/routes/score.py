from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import ScoreOut
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["score"])


@router.get("/score/{username}", response_model=ScoreOut)
async def get_score(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")
    if not developer.score_breakdown:
        raise HTTPException(status_code=404, detail="Score not yet computed for this user")
    return ScoreOut(**developer.score_breakdown)
