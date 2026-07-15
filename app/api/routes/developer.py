from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.developer import DeveloperOut
from app.services.pipeline import DeveloperNotFoundError, get_developer_or_404

router = APIRouter(tags=["developer"])


@router.get("/developer/{username}", response_model=DeveloperOut)
async def get_developer(username: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_developer_or_404(db, username)
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail="Run POST /analyze for this user first")
