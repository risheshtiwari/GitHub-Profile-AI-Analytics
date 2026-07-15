from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import AIAnalysisOut
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["summary"])


@router.get("/summary/{username}", response_model=AIAnalysisOut)
async def get_summary(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")
    if developer.ai_analysis is None:
        raise HTTPException(status_code=404, detail="AI analysis not yet available for this user")
    return developer.ai_analysis
