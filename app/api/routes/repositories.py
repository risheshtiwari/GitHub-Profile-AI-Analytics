from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import RepositoryOut
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["repositories"])


@router.get("/repositories/{username}", response_model=list[RepositoryOut])
async def get_repositories(username: str, db: AsyncSession = Depends(get_db)):
    try:
        developer = await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")
    return developer.repositories
