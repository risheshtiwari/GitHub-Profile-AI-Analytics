from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import InterviewQuestionsOut
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["interview"])


@router.get("/interview/{username}", response_model=InterviewQuestionsOut)
async def get_interview_questions(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")
    if developer.ai_analysis is None or not developer.ai_analysis.interview_questions:
        raise HTTPException(status_code=404, detail="Interview questions not yet available for this user")
    return InterviewQuestionsOut(questions=developer.ai_analysis.interview_questions)
