from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    resume: list[str] = []
    github: list[str] = []
    resume_is_usage: bool = False
    github_repo_count: int = 0
    github_code_share: float = 0.0


class SkillAnalysisOut(BaseModel):
    skill: str
    category: str
    importance: str
    status: str = Field(..., description="strong | partial | weak | missing | unknown")
    match: str = Field(..., description="Human-readable label for `status`")
    score: float
    confidence: str
    evidence: Evidence
    rationale: str


class ProjectAnalysisOut(BaseModel):
    project: str
    source: str = Field(..., description="github | resume")
    relevance: float
    matched_requirements: list[str] = []
    semantic_similarity: float | None = None
    stars: int | None = None


class DiscrepancyOut(BaseModel):
    type: str = Field(..., description="verification_gap | additional_evidence")
    skill: str
    severity: str
    summary: str
    resume_evidence: list[str] = []
    github_evidence: list[str] = []
    note: str


class InterviewQuestionOut(BaseModel):
    category: str
    question: str
    why: str | None = None


class LearningRecommendationOut(BaseModel):
    skill: str
    why: str | None = None
    steps: list[str] = []


class ScoreComponentOut(BaseModel):
    score: float
    weight_percent: float
    contribution: float
    detail: dict[str, Any] = {}


class JobMatchOut(BaseModel):
    github_username: str
    company: str
    role_title: str | None = None
    generated_at: str | None = None

    overall_match: float
    confidence: float
    recommendation: str

    score_breakdown: dict[str, ScoreComponentOut]
    confidence_breakdown: dict[str, Any] = {}

    strong_matches: list[str] = []
    partial_matches: list[str] = []
    weak_matches: list[str] = []
    missing_skills: list[str] = []
    unknown_skills: list[str] = []

    skill_analysis: list[SkillAnalysisOut] = []
    project_analysis: list[ProjectAnalysisOut] = []
    experience_analysis: dict[str, Any] = {}
    evidence_discrepancies: list[DiscrepancyOut] = []

    explanation: str | None = None
    strengths: list[str] = []
    concerns: list[str] = []
    interview_questions: list[InterviewQuestionOut] = []
    learning_recommendations: list[LearningRecommendationOut] = []

    jd_requirements: dict[str, Any] = {}
    resume_signals: dict[str, Any] = {}
    methodology: dict[str, Any] = {}
    disclaimer: str


class JobMatchSummaryOut(BaseModel):
    id: int
    github_username: str
    company: str
    role_title: str | None = None
    overall_match: float
    confidence: float
    recommendation: str
    created_at: datetime

    class Config:
        from_attributes = True
