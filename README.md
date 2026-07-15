# GitHub Developer Analytics & AI Insights Platform

A FastAPI backend that takes a GitHub username, pulls profile/repo/commit data from
the GitHub REST API, computes repository/language/contribution analytics, and layers
an OpenAI-powered engine on top to generate skill assessments, a resume summary, and
personalized interview questions.

See the accompanying **Implementation Guide PDF** for the full architecture writeup.
This README covers running it.

## Quick Start (Docker — recommended)

1. Copy the env template and fill in your keys:
   ```bash
   cp .env.example .env
   ```
   At minimum set:
   - `GITHUB_TOKEN` — a GitHub personal access token (no scopes needed for public
     data). Without this you're limited to 60 requests/hour; with it, 5000/hour.
   - `OPENAI_API_KEY` — your OpenAI API key.
   - `SECRET_KEY` — any long random string, used to sign JWTs.

2. Build and start everything (API + Postgres + Redis):
   ```bash
   docker compose up --build
   ```

3. The API is now live at `http://localhost:8000`. Interactive docs (Swagger UI)
   are auto-generated at `http://localhost:8000/docs`.

## Using the API

1. **Register a user** (write endpoints require a JWT):
   ```bash
   curl -X POST http://localhost:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{"username": "you", "password": "yourpassword"}'
   ```
   This returns an `access_token`.

2. **Analyze a GitHub profile:**
   ```bash
   curl -X POST http://localhost:8000/analyze \
     -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" \
     -d '{"username": "torvalds"}'
   ```
   This can take 10-30+ seconds the first time (it's fetching + analyzing every
   repo). Results are cached in Redis for `CACHE_TTL_SECONDS` (default 1 hour).

3. **Read back the analytics** (no auth needed — read-only):
   ```bash
   curl http://localhost:8000/developer/torvalds
   curl http://localhost:8000/repositories/torvalds
   curl http://localhost:8000/languages/torvalds
   curl http://localhost:8000/activity/torvalds
   curl http://localhost:8000/summary/torvalds
   curl http://localhost:8000/interview/torvalds
   curl http://localhost:8000/score/torvalds
   curl http://localhost:8000/top-projects/torvalds
   ```

4. **Compare two developers** (requires auth, like /analyze):
   ```bash
   curl -X POST http://localhost:8000/compare \
     -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" \
     -d '{"user1": "torvalds", "user2": "gvanrossum"}'
   ```

## Running Locally Without Docker

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# You still need Postgres + Redis running somewhere reachable;
# point DATABASE_URL / REDIS_URL in .env at them.

uvicorn app.main:app --reload
```

## Running Tests

```bash
pip install -r requirements.txt
pytest -v
```

The test suite covers the pure-function analytics modules (`repo_analyzer`,
`language_analyzer`, `activity_analyzer`, `scoring`) with no network or DB
dependency — they run in under a second.

## Design Notes / Known Simplifications

- **Table creation** uses SQLAlchemy's `create_all()` on startup for simplicity.
  For a real production system, switch to Alembic migrations (`alembic init`,
  generate a first revision from the current models, and run `alembic upgrade
  head` in your deploy step instead).
- **`MAX_REPOS_ANALYZED`** (default 30) caps how many repos are deep-analyzed per
  user, sorted by most-recently-pushed. This bounds the number of GitHub API calls
  per `/analyze` request — raise it if you have a high rate limit and don't mind
  slower requests.
- **Testing score** is a heuristic based on repo topics (`pytest`, `ci`, etc.) —
  GitHub's API doesn't expose "does this repo have tests" directly without
  cloning the repo. Documented in `scoring.py` if you want to extend it (e.g. by
  checking for a `tests/` directory via the contents API).
- **AI failures don't fail the whole `/analyze` request** — deterministic
  analytics (repos, languages, activity, scores) are persisted first and are
  useful even if the LLM call fails or times out.

## Next Steps to Harden for Production

- Add Alembic migrations instead of `create_all()`.
- Add per-IP rate limiting (e.g. via `slowapi`) in front of `/analyze`.
- Move the AI + collection phase of `/analyze` to a background task/queue
  (Celery, or FastAPI `BackgroundTasks` for simple cases) and return a job ID
  immediately instead of blocking the HTTP request for the full pipeline.
- Add structured logging (e.g. `structlog`) and request tracing.
