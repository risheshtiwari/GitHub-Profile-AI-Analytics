from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60

    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/analyzer"

    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 3600

    github_token: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    max_repos_analyzed: int = 30

    # ---- Repo Chat (RAG over a single repository) ----
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 512          # text-embedding-3-* supports dim truncation
    embedding_batch_size: int = 64

    ingest_max_files: int = 400              # hard ceiling on files pulled from a repo
    ingest_max_file_bytes: int = 120_000     # skip anything larger (generated/minified)
    ingest_max_total_bytes: int = 8_000_000  # ceiling on total source text ingested
    ingest_max_chunks: int = 1500            # ceiling on chunks embedded per repo
    chunk_target_lines: int = 60
    chunk_overlap_lines: int = 12

    retrieval_top_k: int = 8                 # chunks fed to the LLM
    retrieval_candidate_k: int = 30          # candidates before MMR re-ranking
    retrieval_vector_weight: float = 0.7     # hybrid: 0.7 * vector + 0.3 * lexical
    chat_history_turns: int = 6              # prior turns kept in the prompt
    repo_chat_cache_ttl_seconds: int = 86_400

    # ---- Job match (JD + resume + GitHub) ----
    match_model: str = "gpt-4o-mini"
    resume_max_bytes: int = 2_000_000        # 2 MB ceiling on uploaded PDFs
    resume_max_pages: int = 15
    resume_max_chars: int = 40_000           # text sent to the LLM

    # Deterministic scoring weights. These must sum to 1.0 — the engine asserts
    # it at import time so a bad .env fails loudly instead of silently skewing
    # every candidate's score.
    weight_technical_skills: float = 0.30
    weight_work_experience: float = 0.25
    weight_project_relevance: float = 0.20
    weight_tools_frameworks: float = 0.10
    weight_education: float = 0.05
    weight_engineering_practices: float = 0.10

    # An UNKNOWN skill (no public evidence either way) is not proof of absence,
    # so it counts at half weight in the denominator and contributes nothing to
    # the numerator — it dents the score less than a confirmed gap, and shows up
    # in the confidence figure instead.
    unknown_denominator_weight: float = 0.5

    importance_weight_required: float = 1.0
    importance_weight_preferred: float = 0.6
    importance_weight_nice_to_have: float = 0.3

    jd_cache_ttl_seconds: int = 604_800      # JD parses are safe to cache (no PII)


@lru_cache
def get_settings() -> Settings:
    return Settings()
