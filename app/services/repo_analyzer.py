"""Phase 2 — Repository Analysis.

Pure functions over raw repo dicts (as returned by GitHubClient.get_repos, enriched
with languages/readme flags). No network calls here, which keeps this trivially
unit-testable.
"""

from datetime import datetime, timedelta


def enrich_repo(repo: dict, has_readme: bool, languages: dict[str, int]) -> dict:
    return {
        "name": repo["name"],
        "full_name": repo["full_name"],
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "primary_language": repo.get("language"),
        "languages": languages,
        "topics": repo.get("topics", []),
        "is_archived": repo.get("archived", False),
        "has_readme": has_readme,
        "has_license": bool(repo.get("license")),
        "size_kb": repo.get("size", 0),
        "pushed_at": repo.get("pushed_at"),
        "created_at_gh": repo.get("created_at"),
    }


def repository_summary(repos: list[dict]) -> dict:
    if not repos:
        return {
            "average_size_kb": 0,
            "most_popular": None,
            "most_active": None,
            "archived_count": 0,
            "documentation_score": 0.0,
        }

    avg_size = sum(r["size_kb"] for r in repos) / len(repos)
    most_popular = max(repos, key=lambda r: r["stars"])

    def pushed_dt(r):
        v = r.get("pushed_at")
        if not v:
            return datetime.min
        return v if isinstance(v, datetime) else datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")

    most_active = max(repos, key=pushed_dt)
    archived_count = sum(1 for r in repos if r["is_archived"])
    documented = sum(1 for r in repos if r["has_readme"] and r["has_license"])
    documentation_score = round(100 * documented / len(repos), 1)

    return {
        "average_size_kb": round(avg_size, 1),
        "most_popular": {"name": most_popular["name"], "stars": most_popular["stars"]},
        "most_active": {"name": most_active["name"], "pushed_at": most_active.get("pushed_at")},
        "archived_count": archived_count,
        "documentation_score": documentation_score,
    }


def recent_activity_score(repo: dict, reference: datetime | None = None) -> float:
    """0-1 score: 1.0 if pushed within the last 30 days, decaying to 0 over a year."""
    reference = reference or datetime.utcnow()
    pushed = repo.get("pushed_at")
    if not pushed:
        return 0.0
    pushed_dt = pushed if isinstance(pushed, datetime) else datetime.strptime(pushed, "%Y-%m-%dT%H:%M:%SZ")
    age_days = max((reference - pushed_dt).days, 0)
    if age_days <= 30:
        return 1.0
    if age_days >= 365:
        return 0.0
    return round(1 - (age_days - 30) / (365 - 30), 3)
