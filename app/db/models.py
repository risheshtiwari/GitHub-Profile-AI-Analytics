from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """API consumer account (for JWT auth on write endpoints)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Developer(Base):
    __tablename__ = "developers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    followers: Mapped[int] = mapped_column(Integer, default=0)
    following: Mapped[int] = mapped_column(Integer, default=0)
    public_repos: Mapped[int] = mapped_column(Integer, default=0)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    repositories: Mapped[list["Repository"]] = relationship(
        back_populates="developer", cascade="all, delete-orphan"
    )
    commit_history: Mapped[list["CommitHistory"]] = relationship(
        back_populates="developer", cascade="all, delete-orphan"
    )
    ai_analysis: Mapped["AIAnalysis"] = relationship(
        back_populates="developer", uselist=False, cascade="all, delete-orphan"
    )


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("developer_id", "full_name", name="uq_dev_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    developer_id: Mapped[int] = mapped_column(ForeignKey("developers.id"))

    name: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(300))
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    primary_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    languages: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {lang: bytes}
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    has_readme: Mapped[bool] = mapped_column(Boolean, default=False)
    has_license: Mapped[bool] = mapped_column(Boolean, default=False)
    size_kb: Mapped[int] = mapped_column(Integer, default=0)

    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at_gh: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    developer: Mapped["Developer"] = relationship(back_populates="repositories")


class CommitHistory(Base):
    """Aggregated weekly commit counts across all analyzed repos for a developer."""

    __tablename__ = "commit_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    developer_id: Mapped[int] = mapped_column(ForeignKey("developers.id"))
    week_start: Mapped[datetime] = mapped_column(DateTime)
    count: Mapped[int] = mapped_column(Integer, default=0)

    developer: Mapped["Developer"] = relationship(back_populates="commit_history")


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    developer_id: Mapped[int] = mapped_column(ForeignKey("developers.id"), unique=True)

    summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    strengths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    weaknesses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    likely_expertise: Mapped[list | None] = mapped_column(JSON, nullable=True)
    suggested_learning: Mapped[list | None] = mapped_column(JSON, nullable=True)
    interview_questions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    developer: Mapped["Developer"] = relationship(back_populates="ai_analysis")


# ---------------------------------------------------------------------------
# Repo Chat — RAG over a single repository
# ---------------------------------------------------------------------------


class IndexedRepo(Base):
    """A GitHub repository that has been ingested, chunked and embedded so it
    can be chatted with. One row per (owner, repo, ref)."""

    __tablename__ = "indexed_repos"
    __table_args__ = (UniqueConstraint("full_name", name="uq_indexed_repo_full_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(150), index=True)
    repo: Mapped[str] = mapped_column(String(150), index=True)
    full_name: Mapped[str] = mapped_column(String(300), index=True)

    default_branch: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(150), nullable=True)

    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    languages: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)

    # Structural context injected into every chat prompt
    file_tree: Mapped[list | None] = mapped_column(JSON, nullable=True)
    readme_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # "pending" | "indexing" | "ready" | "failed"
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    file_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dim: Mapped[int] = mapped_column(Integer, default=0)

    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chunks: Mapped[list["RepoChunk"]] = relationship(
        back_populates="repo_ref", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="repo_ref", cascade="all, delete-orphan"
    )


class RepoChunk(Base):
    """One retrievable slice of a source file, with its embedding vector.

    The vector is stored as a JSON float array rather than a pgvector column so
    the project runs on stock Postgres; similarity is computed in Python over an
    in-process cached matrix (see services/vector_store.py).
    """

    __tablename__ = "repo_chunks"
    __table_args__ = (Index("ix_repo_chunks_repo_id_ordinal", "repo_id", "ordinal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("indexed_repos.id"), index=True)

    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500), index=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(300), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, default=1)
    end_line: Mapped[int] = mapped_column(Integer, default=1)

    content: Mapped[str] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)

    repo_ref: Mapped["IndexedRepo"] = relationship(back_populates="chunks")


class ChatSession(Base):
    """A conversation thread bound to one indexed repository."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("indexed_repos.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    repo_ref: Mapped["IndexedRepo"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)

    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retrieved_paths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    standalone_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
