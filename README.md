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

---

## Feature: Chat With a Repository (RAG)

Point the API at **any public GitHub repo URL** and ask questions about it —
what it does, how it does it, and follow-up cross-questions that build on the
previous answers. Answers are grounded in the actual source and cite
`path:start-end` line ranges, so every claim is verifiable.

### How it works

```
repo URL
   |
   v
[1] Ingest      GitHub zipball -> filtered file set (skips node_modules,
   |            lockfiles, minified bundles, binaries) + file tree + README
   |            + dependency manifests                      repo_ingest.py
   v
[2] Chunk       line-windowed slices with overlap; each chunk keeps its
   |            path, line range, and nearest enclosing def/class    chunker.py
   v
[3] Embed       text-embedding-3-small @ 512 dims, batched     embeddings.py
   |            (deterministic offline fallback if no API key)
   v
[4] Store       Postgres: indexed_repos + repo_chunks (JSON vectors)
   |
   v  --- question arrives ---
   |
[5] Condense    follow-up + history -> one standalone query      repo_chat.py
   v
[6] Retrieve    hybrid: 0.7 * cosine + 0.3 * BM25, then MMR   vector_store.py
   v            re-ranking for source diversity
   |
[7] Answer      repo card + numbered code context -> LLM -> cited answer
```

### Why it is built this way

| Decision | Reason |
| --- | --- |
| **Zipball, not the contents API** | One HTTP request instead of hundreds of per-file calls, so a repo can be ingested without shredding the GitHub rate limit. |
| **Hybrid retrieval (vector + BM25)** | Code search needs exact identifiers (`composite_developer_score`) *and* intent ("how does it handle rate limits"). Embeddings are good at the second, BM25 at the first. |
| **MMR re-ranking** | Without it, the top-k is often five overlapping windows of the same file. MMR forces the model to see different parts of the codebase. |
| **Question condensing** | "And where is that called from?" is meaningless to a retriever. Rewriting follow-ups into standalone queries is the single biggest quality lever in multi-turn RAG. |
| **Repo card in every prompt** | File tree + README + manifests are always present, so structural questions ("what is this project?") work even when chunk retrieval misses. |
| **Vectors in a JSON column** | Keeps the stack on stock Postgres — no pgvector, no external vector DB. Similarity runs in Python over an in-process cached matrix. Swap in pgvector when the corpus outgrows it. |
| **Symbol + line range on every chunk** | Enables real citations. `app/router.py:38-52 (def update)` is checkable; "the router file" is not. |

### Endpoints

| Method & Path | Purpose |
| --- | --- |
| `POST /repo-chat/index` | Ingest a repo (background by default; `wait: true` to block) |
| `GET /repo-chat/repos` | List indexed repositories |
| `GET /repo-chat/repos/{owner}/{repo}` | Index status + stats (poll this after indexing) |
| `DELETE /repo-chat/repos/{owner}/{repo}` | Drop an index |
| `GET /repo-chat/repos/{owner}/{repo}/overview` | AI brief: what it does, how it works, architecture, entry points, suggested questions |
| `POST /repo-chat/sessions` | Open a conversation (indexes the repo if needed) |
| `GET /repo-chat/sessions` | List your conversations |
| `GET /repo-chat/sessions/{id}/messages` | Full transcript with citations |
| `POST /repo-chat/sessions/{id}/messages` | Ask a question (follow-ups resolved against history) |
| `POST /repo-chat/sessions/{id}/messages/stream` | Same, streamed over SSE |
| `DELETE /repo-chat/sessions/{id}` | Delete a conversation |
| `POST /repo-chat/ask` | One-shot: index + session + question in a single call |

### Walkthrough

```bash
TOKEN=<your access_token from /auth/register>

# 1. Index a repo (returns immediately, indexes in the background)
curl -X POST http://localhost:8000/repo-chat/index \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/tiangolo/fastapi"}'

# 2. Poll until status is "ready"
curl http://localhost:8000/repo-chat/repos/tiangolo/fastapi

# 3. Get the orientation brief
curl http://localhost:8000/repo-chat/repos/tiangolo/fastapi/overview

# 4. Open a session
SESSION=$(curl -s -X POST http://localhost:8000/repo-chat/sessions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/tiangolo/fastapi"}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

# 5. Ask — then cross-question; turn 2 resolves "that" against turn 1
curl -X POST http://localhost:8000/repo-chat/sessions/$SESSION/messages \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question": "How does dependency injection work here?"}'

curl -X POST http://localhost:8000/repo-chat/sessions/$SESSION/messages \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question": "Where is that cached, and what invalidates it?"}'
```

A response looks like:

```json
{
  "session_id": "0f2c...",
  "repository": "tiangolo/fastapi",
  "question": "Where is that cached, and what invalidates it?",
  "standalone_question": "Where are resolved FastAPI dependencies cached and what invalidates the cache?",
  "answer": "Resolved dependencies are cached per-request in `solve_dependencies` [2] ...",
  "citations": [
    {"n": 2, "path": "fastapi/dependencies/utils.py", "start_line": 512,
     "end_line": 571, "symbol": "async def solve_dependencies", "relevance": 0.87}
  ],
  "sources": ["fastapi/dependencies/utils.py", "fastapi/routing.py"],
  "latency_ms": 3120
}
```

### Streaming (SSE)

`POST /repo-chat/sessions/{id}/messages/stream` emits a `citations` event first
(so a UI can render sources while the answer types out), then `token` events,
then `done`.

### Notes and limits

- **Public repos only** — the ingest uses your `GITHUB_TOKEN`, so private repos
  work only if that token can read them.
- **No OpenAI key?** Indexing and retrieval still run via the `HashingEmbedder`
  fallback; only the final answer generation needs the LLM. Tests exploit this
  to run for free.
- **Budgets** (`INGEST_MAX_FILES`, `INGEST_MAX_CHUNKS`) cap ingestion, spending
  the budget on READMEs and manifests first, then code, then config.
- **Re-indexing** replaces chunks wholesale and invalidates the in-process
  matrix cache. There is no incremental/diff indexing yet.

### Testing

```bash
pytest tests/test_repo_chat.py -v
```

31 tests over URL parsing, file filtering, chunk line-range integrity, symbol
detection, BM25 ranking, MMR diversification, hybrid search and prompt
assembly — all offline.

---

---

## The Console (web UI)

There is a full web interface — no Swagger, no curl. It is plain HTML, CSS and
ES modules served by FastAPI itself, so there is **no Node, no npm install and
no build step**: `docker compose up` serves the API and the UI together.

Open **http://localhost:8000** and it redirects to the console at `/ui/`.

```
┌──────────────────────────────────────────────────────────────┐
│ Bench                                    ● API connected  ▸  │
├──────────────┬───────────────────────────────────────────────┤
│ 01 Analyze   │  Read a developer's work                      │
│ 02 Compare   │  ┌─────────────────────────────────────────┐  │
│ 03 Repo chat │  │ github username        [ Run analysis ] │  │
│              │  └─────────────────────────────────────────┘  │
│              │  commit strip · score columns · language mix  │
│              │  résumé summary · interview questions · repos │
└──────────────┴───────────────────────────────────────────────┘
```

### What each screen does

**01 · Analyze a developer** — one username runs the whole pipeline, then
renders it: a 52-week commit strip, the five score sub-components as columns,
language mix, monthly trend, the AI résumé summary and skill assessment,
personalised interview questions, ranked top projects, and the full repo table.

**02 · Compare two developers** — both profiles on shared axes, so the gaps are
readable rather than buried in two JSON blobs.

**03 · Chat with a repository** — paste a repo URL. Indexing runs in the
background with a live status pill; when it is ready you get an AI brief of what
the project does and how, plus questions generated for that specific codebase.
Ask anything, then cross-question it.

### The part worth demoing

Every answer's citations are **expandable**. Click `[2]` in an answer and the
actual retrieved lines open beneath it, with their real line numbers from the
real file:

```
[2] app/router.py                    def update            38–52
 38 │     def update(self, arm, reward):
 39 │         """Importance-weighted reward update."""
 40 │         index = self.arms.index(arm)
```

And when a follow-up gets rewritten for retrieval, the UI shows you what it
actually searched for — `Searched for: EXP3 importance weighted reward update` —
so the retrieval step is visible instead of hidden.

Answers stream by default (citations land first, then the text types in).
Uncheck **stream** next to the Ask button to use the buffered endpoint instead.

### Design notes

- **No frontend framework and no bundler.** ES modules over HTTP. The whole UI
  is ~1,900 lines across 8 files and loads in one round trip per file.
- **Charts are hand-drawn SVG** (`js/charts.js`) in a two-ink hatched language
  rather than a rainbow palette — with twelve languages in a pie chart, colour
  tells you nothing that rank and magnitude don't tell you better.
- **Auth is a gate, not a wall.** Read endpoints work signed out; the first
  write action opens the account dialog and explains why.

### Running the UI against a separate API

The API sends permissive CORS headers, so you can also serve the frontend
standalone while pointing at a remote API:

```bash
cd frontend && python -m http.server 5173
```

Then change the `BASE` constant handling in `js/api.js` (paths are relative by
default, which is what makes the bundled case zero-config).

---

---

## Feature: Candidate Job-Fit Analysis (JD + Resume + GitHub)

Upload a resume PDF, paste a job description, give a GitHub username. The system
reads all three, then produces an **explainable** fit report: a match percentage
you can audit line by line, evidence for every skill verdict, and an honest
distinction between *not demonstrated* and *no public evidence*.

Screen **04 · Match a candidate to a role** in the console, or
`POST /job-match`.

### The core rule: the model does not set the score

```
   JD text  ─────► jd_parser (LLM)      ─┐
   resume PDF ───► resume_parser (LLM)  ─┤  extraction only
   username ─────► collect_and_analyze  ─┘  (deterministic, cached)
                                    │
                                    ▼
                   match_engine.compute_match   ← every number is computed here
                                    │
                                    ▼
                narration (LLM): explanation, questions, roadmap
                        (receives the scores; cannot change them)
```

The language model reads, extracts, and explains. Arithmetic happens in
`match_engine.py`, which contains no LLM call at all. Same inputs, same score,
every time — and there is a test asserting a narration that claims a different
percentage cannot move the result.

### Weighted scoring

| Component | Weight | Evidence it draws on |
| --- | --- | --- |
| Technical skills | 30% | Languages, databases, cloud, domain skills — from both sources |
| Work experience | 25% | Stated durations vs the JD's minimum, plus domain overlap |
| Project relevance | 20% | Mean relevance of the three most relevant projects |
| Tools & frameworks | 10% | Frameworks and tooling requirements |
| Education | 5% | Highest level vs the JD's requirement, plus field match |
| Engineering practices | 10% | READMEs, tests, licensing, commit consistency |

Weights live in `.env` (`WEIGHT_TECHNICAL_SKILLS` and friends) and must sum to
1.0 — `match_engine` raises at import if they don't, so a bad config fails
loudly instead of quietly skewing every candidate.

### Missing vs unknown — the distinction that matters

| Verdict | Meaning | Effect on score |
| --- | --- | --- |
| **Strong** | Evidenced in both the resume and public GitHub | Full credit |
| **Partial** | Evidenced in one source | Partial credit |
| **Weak** | Listed in the resume, never described as used | Small credit |
| **Not demonstrated** | Absent, *while comparable skills in the same category are evidenced* | Zero, full weight |
| **No public evidence** | Absent, and the silence is uninformative | Zero, **half** weight — and it lowers confidence |

A JD asking for CUDA against a candidate with no CUDA anywhere yields
*"No public evidence of CUDA either way. This is a verification gap to raise in
interview, not a demonstrated gap."* — never "the candidate does not know CUDA".

MISSING has to be earned: it requires at least two peer skills in the same
category to be evidenced, and it is never applied to engineering practices
(nobody's code review habits are visible from a public profile).

### Evidence for every verdict

Each skill expands to show exactly where it was found:

```
Python                    Strong    required    97    conf: High
  Resume                              GitHub
  · Listed under languages            · Python is 92.3% of public code
  · Used in a role at Zeta Systems     · Repository face-recognition (topic, 120★)
```

### Discrepancy detection, both directions

- **Verification gap** — the resume describes using a skill that public work
  does not corroborate. Flagged only when the profile has enough public code for
  the silence to mean anything, and worded as a gap to confirm in interview,
  never as an accusation. There is a test asserting the output contains no
  accusatory vocabulary.
- **Additional evidence** — public work evidences a skill the resume omits: the
  candidate may be underselling themselves.

### Fairness and data handling

- Gender, age, date of birth, marital status, nationality, religion, caste,
  ethnicity, political affiliation and photo references are **stripped from the
  text before it reaches the model**, and the prompt forbids extracting them.
  `ResumeProfile` has no field that could hold one.
- Email addresses and phone numbers are redacted; the API response and stored
  report carry neither, nor the candidate's name.
- The PDF is parsed **in memory** and never written to disk. Only the derived
  report is stored. Resume text is never logged — only counts (pages, roles,
  skills).
- Resume parses are deliberately **not** cached; JD parses are, since a JD
  contains no personal data.
- Every report carries a disclaimer that this is decision support, not a
  decision.

### API

```
POST   /job-match                 multipart: username, company, job_description, resume_pdf
GET    /job-match/reports         your previous reports
GET    /job-match/reports/{id}    one report in full
DELETE /job-match/reports/{id}    delete a report
```

```bash
curl -X POST http://localhost:8000/job-match \
  -H "Authorization: Bearer $TOKEN" \
  -F "username=torvalds" \
  -F "company=Acme Corp" \
  -F "job_description=$(cat jd.txt)" \
  -F "resume_pdf=@resume.pdf;type=application/pdf"
```

Returns `overall_match`, `confidence`, `recommendation`, `score_breakdown`
(score × weight = contribution per component), `skill_analysis` with evidence,
`project_analysis`, `experience_analysis`, `evidence_discrepancies`,
`interview_questions`, `learning_recommendations`, `methodology` and
`disclaimer`.

Errors: `422` for an unreadable or non-PDF resume and for an unusable JD, `413`
for a file over 2 MB, `404` for an unknown GitHub user, `401` unauthenticated.

---

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

- **Repo Chat vectors live in a JSON column**, not pgvector. Similarity is
  computed in Python over an in-process cached matrix, which is fine up to a few
  thousand chunks per repo. Beyond that, move `repo_chunks.embedding` to a
  `vector(512)` column (swap the Postgres image for `pgvector/pgvector:pg16`)
  and push the ranking into SQL.
- **Chunking is line-windowed**, not AST-based. Tree-sitter would give cleaner
  function-level boundaries; the current approach keeps zero extra dependencies
  and preserves exact line ranges for citations.

- **Job-fit scoring is rules-based, not learned.** The weights are a defensible
  default, not a calibrated model — there is no labelled hiring-outcome data
  behind them. They are exposed in `.env` precisely because any given team will
  want to argue with them.
- **Resume parsing needs a text-based PDF.** Scanned resumes return a clear
  error rather than silently producing an empty profile; OCR is not wired in.

## Next Steps to Harden for Production

- Add Alembic migrations instead of `create_all()`.
- Add per-IP rate limiting (e.g. via `slowapi`) in front of `/analyze`.
- Move the AI + collection phase of `/analyze` to a background task/queue
  (Celery, or FastAPI `BackgroundTasks` for simple cases) and return a job ID
  immediately instead of blocking the HTTP request for the full pipeline.
- Add structured logging (e.g. `structlog`) and request tracing.
