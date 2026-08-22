from app.services import scoring


def test_rank_projects_orders_by_score_desc():
    repos = [
        {"name": "low", "full_name": "u/low", "project_score": 10, "stars": 1, "forks": 0},
        {"name": "high", "full_name": "u/high", "project_score": 90, "stars": 100, "forks": 10},
    ]
    ranked = scoring.rank_projects(repos)
    assert ranked[0]["name"] == "high"
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2


def test_documentation_score_all_documented():
    repos = [{"has_readme": True, "has_license": True} for _ in range(4)]
    assert scoring.documentation_score(repos) == 100.0


def test_documentation_score_none_documented():
    repos = [{"has_readme": False, "has_license": False} for _ in range(4)]
    assert scoring.documentation_score(repos) == 0.0


def test_testing_score_detects_topic_keywords():
    repos = [
        {"topics": ["pytest", "backend"]},
        {"topics": ["frontend"]},
    ]
    assert scoring.testing_score(repos) == 50.0
