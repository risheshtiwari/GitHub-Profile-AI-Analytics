"""Bonus endpoint (Section 12 of the guide) — compares two developers side by side."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.developer import CompareRequest
from app.services.pipeline import DeveloperNotFoundError, collect_and_analyze, persist_analysis

router = APIRouter(tags=["compare"])


def _build_comparison(a: dict, b: dict) -> dict:
    return {
        "language_expertise": {
            a["profile"]["github_username"]: a["languages"]["distribution_percent"],
            b["profile"]["github_username"]: b["languages"]["distribution_percent"],
        },
        "repository_quality": {
            a["profile"]["github_username"]: a["repository_summary"],
            b["profile"]["github_username"]: b["repository_summary"],
        },
        "contribution_consistency": {
            a["profile"]["github_username"]: {
                "longest_streak_weeks": a["activity"]["longest_streak_weeks"],
                "average_commits_per_week": a["activity"]["average_commits_per_week"],
            },
            b["profile"]["github_username"]: {
                "longest_streak_weeks": b["activity"]["longest_streak_weeks"],
                "average_commits_per_week": b["activity"]["average_commits_per_week"],
            },
        },
        "developer_score": {
            a["profile"]["github_username"]: a["developer_score"],
            b["profile"]["github_username"]: b["developer_score"],
        },
        "verdict": (
            f"{a['profile']['github_username']} scores higher overall"
            if a["developer_score"]["overall_score"] >= b["developer_score"]["overall_score"]
            else f"{b['profile']['github_username']} scores higher overall"
        ),
    }


@router.post("/compare")
async def compare_developers(
    payload: CompareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_a = await collect_and_analyze(payload.user1)
        analysis_b = await collect_and_analyze(payload.user2)
    except DeveloperNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"GitHub user '{exc}' not found")

    await persist_analysis(db, analysis_a)
    await persist_analysis(db, analysis_b)

    return _build_comparison(analysis_a, analysis_b)
