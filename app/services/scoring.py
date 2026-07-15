"""Phase 8 & 9 — Project Ranking and Composite Developer Score.

All formulas are pure functions with documented, tunable weights.
"""

import math

TESTING_KEYWORDS = {"testing", "unit-testing", "ci", "continuous-integration", "pytest", "jest"}


def _normalize(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return min(value / max_value, 1.0)


def project_score(repo: dict, max_stars: int, max_forks: int, activity_score: float) -> float:
    """Project Score = 0.4*stars + 0.2*forks + 0.2*recent_activity + 0.2*readme_quality"""
    stars_norm = _normalize(repo["stars"], max_stars)
    forks_norm = _normalize(repo["forks"], max_forks)
    readme_quality = 1.0 if (repo["has_readme"] and repo["has_license"]) else (0.5 if repo["has_readme"] else 0.0)

    score = (
        0.4 * stars_norm
        + 0.2 * forks_norm
        + 0.2 * activity_score
        + 0.2 * readme_quality
    )
    return round(score * 100, 1)


def rank_projects(repos: list[dict]) -> list[dict]:
    ranked = sorted(repos, key=lambda r: r.get("project_score", 0), reverse=True)
    return [
        {
            "rank": i + 1,
            "name": r["name"],
            "full_name": r["full_name"],
            "project_score": r.get("project_score", 0),
            "stars": r["stars"],
            "forks": r["forks"],
        }
        for i, r in enumerate(ranked)
    ]


def consistency_score(longest_streak_weeks: int, inactive_period_count: int, total_weeks: int = 52) -> float:
    """Reward long active streaks, penalize frequent long inactive gaps."""
    if total_weeks == 0:
        return 0.0
    streak_component = _normalize(longest_streak_weeks, total_weeks) * 70
    gap_penalty = min(inactive_period_count * 10, 30)
    return round(max(streak_component + 30 - gap_penalty, 0), 1)


def popularity_score(total_stars: int, followers: int) -> float:
    """Log-scaled so a handful of very popular repos don't completely dominate the score."""
    star_component = min(math.log10(total_stars + 1) / math.log10(10000), 1.0) * 70
    follower_component = min(math.log10(followers + 1) / math.log10(50000), 1.0) * 30
    return round(star_component + follower_component, 1)


def code_diversity_score(language_diversity: float) -> float:
    """language_diversity is already 0-100 (entropy-based), pass through directly."""
    return round(language_diversity, 1)


def documentation_score(repos: list[dict]) -> float:
    if not repos:
        return 0.0
    documented = sum(1 for r in repos if r["has_readme"] and r["has_license"])
    return round(100 * documented / len(repos), 1)


def testing_score(repos: list[dict]) -> float:
    """Heuristic: % of repos whose topics mention testing/CI. Documented as an
    approximation — a deeper version would inspect repo contents for test dirs
    and CI config files."""
    if not repos:
        return 0.0
    with_tests = sum(
        1 for r in repos if set(t.lower() for t in (r.get("topics") or [])) & TESTING_KEYWORDS
    )
    return round(100 * with_tests / len(repos), 1)


def composite_developer_score(
    consistency: float,
    popularity: float,
    code_diversity: float,
    documentation: float,
    testing: float,
) -> dict:
    """Weighted roll-up. Weights sum to 1.0 — adjust here if you want to emphasize
    a different trait (e.g. give testing more weight for a QA-focused profile)."""
    weights = {
        "consistency": 0.25,
        "popularity": 0.25,
        "code_diversity": 0.20,
        "documentation": 0.15,
        "testing": 0.15,
    }
    overall = (
        weights["consistency"] * consistency
        + weights["popularity"] * popularity
        + weights["code_diversity"] * code_diversity
        + weights["documentation"] * documentation
        + weights["testing"] * testing
    )
    return {
        "overall_score": round(overall, 1),
        "consistency": consistency,
        "popularity": popularity,
        "code_diversity": code_diversity,
        "documentation": documentation,
        "testing": testing,
    }
