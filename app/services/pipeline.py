"""Orchestrates the full analysis pipeline: collect -> analyze -> score -> persist.

This is what POST /analyze calls. Keeping it separate from the route handler makes
it reusable from /compare as well, and easy to unit test with a fake GitHubClient.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIAnalysis, CommitHistory, Developer, Repository
from app.services import activity_analyzer, language_analyzer, repo_analyzer, scoring
from app.services.cache import cache_get, cache_set
from app.services.github_client import GitHubClient, GitHubNotFoundError


class DeveloperNotFoundError(Exception):
    pass


async def collect_and_analyze(username: str) -> dict:
    """Pure collection + deterministic analytics (no AI, no DB). Cached in Redis."""
    cache_key = f"analysis:{username.lower()}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    client = GitHubClient()
    try:
        try:
            profile = await client.get_user(username)
        except GitHubNotFoundError:
            raise DeveloperNotFoundError(username)

        raw_repos = await client.get_repos(username)

        enriched_repos = []
        per_repo_weekly = []
        for r in raw_repos:
            full_name = r["full_name"]
            languages = await client.get_languages(full_name)
            has_readme = await client.has_readme(full_name)
            enriched = repo_analyzer.enrich_repo(r, has_readme, languages)
            enriched_repos.append(enriched)

            weekly = await client.get_weekly_commit_activity(full_name)
            per_repo_weekly.append(weekly)

        # ---- Phase 2: repository analysis ----
        repo_summary = repo_analyzer.repository_summary(enriched_repos)
        max_stars = max((r["stars"] for r in enriched_repos), default=0) or 1
        max_forks = max((r["forks"] for r in enriched_repos), default=0) or 1
        for r in enriched_repos:
            activity_score = repo_analyzer.recent_activity_score(r)
            r["project_score"] = scoring.project_score(r, max_stars, max_forks, activity_score)

        # ---- Phase 3: language analytics ----
        lang_totals = language_analyzer.aggregate_languages([r["languages"] for r in enriched_repos])
        languages_out = {
            "distribution_percent": language_analyzer.language_distribution_percent(lang_totals),
            "primary_language": max(lang_totals, key=lang_totals.get) if lang_totals else None,
            "language_diversity_score": language_analyzer.language_diversity_score(lang_totals),
            "backend_frontend_ratio": language_analyzer.backend_frontend_ratio(lang_totals),
            "ai_ml_ecosystem_detected": language_analyzer.detect_ai_ml_ecosystem(
                [r["topics"] for r in enriched_repos],
                [r["primary_language"] for r in enriched_repos],
            ),
        }

        # ---- Phase 4: contribution analytics ----
        merged_weeks = activity_analyzer.merge_weekly_activity(per_repo_weekly)
        activity_out = {
            "commits_per_week": activity_analyzer.commits_per_week_series(merged_weeks),
            "commits_per_month": activity_analyzer.commits_per_month(merged_weeks),
            "longest_streak_weeks": activity_analyzer.longest_streak_weeks(merged_weeks),
            "most_active_weekday": activity_analyzer.most_active_weekday(merged_weeks),
            "average_commits_per_week": activity_analyzer.average_commits_per_week(merged_weeks),
            "inactive_periods": activity_analyzer.inactive_periods(merged_weeks),
        }

        # ---- Phase 8: project ranking ----
        top_projects = scoring.rank_projects(enriched_repos)

        # ---- Phase 9: composite developer score ----
        consistency = scoring.consistency_score(
            activity_out["longest_streak_weeks"], len(activity_out["inactive_periods"])
        )
        popularity = scoring.popularity_score(
            sum(r["stars"] for r in enriched_repos), profile.get("followers", 0)
        )
        code_diversity = scoring.code_diversity_score(languages_out["language_diversity_score"])
        documentation = scoring.documentation_score(enriched_repos)
        testing = scoring.testing_score(enriched_repos)
        dev_score = scoring.composite_developer_score(
            consistency, popularity, code_diversity, documentation, testing
        )

        result = {
            "profile": {
                "github_username": profile["login"],
                "name": profile.get("name"),
                "bio": profile.get("bio"),
                "avatar_url": profile.get("avatar_url"),
                "followers": profile.get("followers", 0),
                "following": profile.get("following", 0),
                "public_repos": profile.get("public_repos", 0),
            },
            "repositories": enriched_repos,
            "repository_summary": repo_summary,
            "languages": languages_out,
            "activity": activity_out,
            "top_projects": top_projects,
            "developer_score": dev_score,
        }
        await cache_set(cache_key, result)
        return result
    finally:
        await client.close()


async def persist_analysis(db: AsyncSession, analysis: dict) -> Developer:
    profile = analysis["profile"]
    result = await db.execute(
        select(Developer).where(Developer.github_username == profile["github_username"])
    )
    developer = result.scalar_one_or_none()
    if developer is None:
        developer = Developer(github_username=profile["github_username"])
        db.add(developer)

    developer.name = profile.get("name")
    developer.bio = profile.get("bio")
    developer.avatar_url = profile.get("avatar_url")
    developer.followers = profile.get("followers", 0)
    developer.following = profile.get("following", 0)
    developer.public_repos = profile.get("public_repos", 0)
    developer.score = analysis["developer_score"]["overall_score"]
    developer.score_breakdown = analysis["developer_score"]
    developer.updated_at = datetime.utcnow()

    await db.flush()  # ensure developer.id is populated

    # Replace repositories wholesale on re-analysis
    await db.execute(Repository.__table__.delete().where(Repository.developer_id == developer.id))
    for r in analysis["repositories"]:
        db.add(Repository(
            developer_id=developer.id,
            name=r["name"],
            full_name=r["full_name"],
            stars=r["stars"],
            forks=r["forks"],
            open_issues=r["open_issues"],
            primary_language=r["primary_language"],
            languages=r["languages"],
            topics=r["topics"],
            is_archived=r["is_archived"],
            has_readme=r["has_readme"],
            has_license=r["has_license"],
            size_kb=r["size_kb"],
            pushed_at=GitHubClient.parse_gh_datetime(r.get("pushed_at")) if isinstance(r.get("pushed_at"), str) else r.get("pushed_at"),
            created_at_gh=GitHubClient.parse_gh_datetime(r.get("created_at_gh")) if isinstance(r.get("created_at_gh"), str) else r.get("created_at_gh"),
            project_score=r["project_score"],
        ))

    await db.execute(CommitHistory.__table__.delete().where(CommitHistory.developer_id == developer.id))
    for point in analysis["activity"]["commits_per_week"]:
        db.add(CommitHistory(
            developer_id=developer.id,
            week_start=datetime.fromisoformat(point["week_start"]),
            count=point["count"],
        ))

    await db.commit()
    await db.refresh(developer)
    return developer


async def get_developer_or_404(db: AsyncSession, username: str) -> Developer:
    result = await db.execute(select(Developer).where(Developer.github_username == username))
    developer = result.scalar_one_or_none()
    if developer is None:
        raise DeveloperNotFoundError(username)
    return developer
