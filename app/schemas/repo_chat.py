from datetime import datetime

from pydantic import BaseModel, Field


class IndexRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/tiangolo/fastapi"])
    ref: str | None = Field(None, description="Branch, tag or commit SHA. Defaults to the repo's default branch.")
    force: bool = Field(False, description="Re-index even if this repo is already indexed.")
    wait: bool = Field(False, description="Run indexing inline instead of as a background job.")


class IndexStatusOut(BaseModel):
    full_name: str
    status: str
    ref: str | None = None
    description: str | None = None
    primary_language: str | None = None
    stars: int = 0
    file_count: int = 0
    chunk_count: int = 0
    total_bytes: int = 0
    embedding_model: str | None = None
    error: str | None = None
    indexed_at: datetime | None = None
    default_branch: str | None = None
    # Null until the first successful index, so these must be optional.
    topics: list[str] | None = None
    file_tree: list[str] | None = None
    coverage: dict | None = None   # tells you if the chunk budget truncated the repo

    class Config:
        from_attributes = True


class SessionCreateRequest(BaseModel):
    repo_url: str
    ref: str | None = None
    title: str | None = None


class SessionOut(BaseModel):
    id: str
    repository: str
    title: str | None = None
    message_count: int = 0
    created_at: datetime
    last_active_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, examples=["How does the retrieval pipeline work?"])
    top_k: int | None = Field(None, ge=1, le=20, description="Override how many chunks are retrieved.")


class Citation(BaseModel):
    n: int
    path: str
    start_line: int
    end_line: int
    symbol: str | None = None
    language: str | None = None
    content: str | None = None   # the cited lines themselves, for display
    relevance: float | None = None


class ChatAnswerOut(BaseModel):
    session_id: str
    repository: str
    question: str
    standalone_question: str | None = None
    answer: str
    citations: list[Citation] = []
    sources: list[str] = []
    latency_ms: int | None = None


class AskRequest(BaseModel):
    """One-shot convenience: index if needed, open a session if needed, ask."""

    repo_url: str
    question: str = Field(..., min_length=2)
    session_id: str | None = None
    ref: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[Citation] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArchitectureComponent(BaseModel):
    component: str
    responsibility: str
    path: str | None = None


class RepoOverviewOut(BaseModel):
    repository: str
    what_it_does: str | None = None
    how_it_works: list[str] = []
    architecture: list[ArchitectureComponent] = []
    tech_stack: list[str] = []
    entry_points: list[str] = []
    notable_patterns: list[str] = []
    suggested_questions: list[str] = []
