from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import (
    activity,
    analyze,
    auth,
    compare,
    developer,
    interview,
    languages,
    repositories,
    score,
    summary,
    top_projects,
)
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="GitHub Developer Analytics & AI Insights Platform",
    description="Analyzes a GitHub profile and generates repository, language, "
                "and contribution analytics plus AI-powered skill insights.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(developer.router)
app.include_router(repositories.router)
app.include_router(languages.router)
app.include_router(activity.router)
app.include_router(summary.router)
app.include_router(interview.router)
app.include_router(score.router)
app.include_router(top_projects.router)
app.include_router(compare.router)


@app.get("/", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "github-developer-analytics"}
