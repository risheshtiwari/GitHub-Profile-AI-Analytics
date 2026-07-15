from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
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
