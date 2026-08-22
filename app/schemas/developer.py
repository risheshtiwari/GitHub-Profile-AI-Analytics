from datetime import datetime

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    username: str


class CompareRequest(BaseModel):
    user1: str
    user2: str


class RepositoryOut(BaseModel):
    name: str
    full_name: str
    stars: int
    forks: int
    open_issues: int
    primary_language: str | None
    is_archived: bool
    has_readme: bool
    has_license: bool
    size_kb: int
    pushed_at: datetime | None
    project_score: float | None

    class Config:
        from_attributes = True


class DeveloperOut(BaseModel):
    github_username: str
    name: str | None
    bio: str | None
    avatar_url: str | None
    followers: int
    following: int
    public_repos: int
    score: float | None
    updated_at: datetime

    class Config:
        from_attributes = True


class LanguageStatsOut(BaseModel):
    distribution_percent: dict[str, float]
    primary_language: str | None
    language_diversity_score: float
    backend_frontend_ratio: dict[str, float]
    ai_ml_ecosystem_detected: list[str]


class ActivityOut(BaseModel):
    commits_per_week: list[dict]
    commits_per_month: dict[str, int]
    longest_streak_weeks: int
    most_active_weekday: str | None
    average_commits_per_week: float
    inactive_periods: list[dict]


class ScoreOut(BaseModel):
    overall_score: float
    consistency: float
    popularity: float
    code_diversity: float
    documentation: float
    testing: float


class TopProjectOut(BaseModel):
    rank: int
    name: str
    full_name: str
    project_score: float
    stars: int
    forks: int


class AIAnalysisOut(BaseModel):
    summary: str | None
    strengths: list[str] | None
    weaknesses: list[str] | None
    likely_expertise: list[str] | None
    suggested_learning: list[str] | None

    class Config:
        from_attributes = True


class InterviewQuestionsOut(BaseModel):
    questions: list[str]
