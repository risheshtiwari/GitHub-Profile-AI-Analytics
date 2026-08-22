from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import TopProjectOut
from app.services import scoring
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["top-projects"])


@router.get("/top-projects/{username}", response_model=list[TopProjectOut])
async def get_top_projects(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")

    repos = [
        {
            "name": r.name,
            "full_name": r.full_name,
            "project_score": r.project_score or 0,
            "stars": r.stars,
            "forks": r.forks,
        }
        for r in developer.repositories
    ]
    return scoring.rank_projects(repos)
