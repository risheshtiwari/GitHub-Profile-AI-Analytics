from datetime import datetime, timedelta

from app.services import activity_analyzer, language_analyzer, repo_analyzer, scoring


def test_language_distribution_percent():
    totals = {"Python": 80, "JavaScript": 20}
    dist = language_analyzer.language_distribution_percent(totals)
    assert dist["Python"] == 80.0
    assert dist["JavaScript"] == 20.0


def test_language_diversity_single_language_is_zero():
    assert language_analyzer.language_diversity_score({"Python": 100}) == 0.0


def test_language_diversity_multiple_languages_positive():
    score = language_analyzer.language_diversity_score({"Python": 50, "Go": 50})
    assert score > 0


def test_backend_frontend_ratio():
    totals = {"Python": 60, "JavaScript": 40}
    ratio = language_analyzer.backend_frontend_ratio(totals)
    assert ratio["backend_percent"] == 60.0
    assert ratio["frontend_percent"] == 40.0


def test_repository_summary_empty():
    summary = repo_analyzer.repository_summary([])
    assert summary["archived_count"] == 0
    assert summary["documentation_score"] == 0.0


def test_repository_summary_picks_most_popular():
    repos = [
        {"name": "a", "stars": 5, "size_kb": 100, "is_archived": False, "has_readme": True,
         "has_license": True, "pushed_at": "2024-01-01T00:00:00Z"},
        {"name": "b", "stars": 50, "size_kb": 200, "is_archived": False, "has_readme": True,
         "has_license": False, "pushed_at": "2024-06-01T00:00:00Z"},
    ]
    summary = repo_analyzer.repository_summary(repos)
    assert summary["most_popular"]["name"] == "b"


def test_recent_activity_score_recent_is_high():
    repo = {"pushed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert repo_analyzer.recent_activity_score(repo) == 1.0


def test_recent_activity_score_old_is_zero():
    old_date = (datetime.utcnow() - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo = {"pushed_at": old_date}
    assert repo_analyzer.recent_activity_score(repo) == 0.0


def test_merge_weekly_activity_sums_repos():
    week_ts = 1700000000
    repo1 = [{"week": week_ts, "total": 3, "days": [1, 0, 0, 1, 1, 0, 0]}]
    repo2 = [{"week": week_ts, "total": 2, "days": [0, 1, 0, 0, 0, 1, 0]}]
    merged = activity_analyzer.merge_weekly_activity([repo1, repo2])
    assert merged[week_ts]["total"] == 5


def test_longest_streak_weeks():
    merged = {
        1: {"total": 1, "days": [0] * 7},
        2: {"total": 1, "days": [0] * 7},
        3: {"total": 0, "days": [0] * 7},
        4: {"total": 1, "days": [0] * 7},
    }
    assert activity_analyzer.longest_streak_weeks(merged) == 2


def test_project_score_bounds():
    repo = {"stars": 100, "forks": 50, "has_readme": True, "has_license": True}
    score = scoring.project_score(repo, max_stars=100, max_forks=50, activity_score=1.0)
    assert score == 100.0


def test_composite_developer_score_weights_sum_correctly():
    result = scoring.composite_developer_score(
        consistency=100, popularity=100, code_diversity=100, documentation=100, testing=100
    )
    assert result["overall_score"] == 100.0
