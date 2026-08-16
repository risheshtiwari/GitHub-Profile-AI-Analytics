from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    activity,
    analyze,
    auth,
    compare,
    developer,
    interview,
    job_match,
    languages,
    repo_chat,
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
                "and contribution analytics plus AI-powered skill insights. Also supports "
                "\"chat with a repository\": point it at any GitHub repo URL and ask "
                "questions about what the code does and how it works.",
    version="2.0.0",
    lifespan=lifespan,
)

# The bundled UI is served from the same origin, so it needs no CORS. This is
# here so you can also run the frontend from a separate dev server (e.g.
# `python -m http.server` inside ./frontend) while pointing at this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(repo_chat.router)
app.include_router(job_match.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "github-developer-analytics"}


# --------------------------------------------------------------------------- #
# Frontend
# --------------------------------------------------------------------------- #
# The single-page console lives in ./frontend and is served as static files, so
# there is no Node build step: one `docker compose up` serves both API and UI.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/ui/")

else:  # pragma: no cover - fallback when only the API is deployed
    @app.get("/", tags=["health"])
    async def root():
        return {"status": "ok", "service": "github-developer-analytics", "docs": "/docs"}
