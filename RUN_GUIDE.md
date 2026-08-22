# Run &amp; Test Guide

Everything below assumes you are in the project root (the folder with
`docker-compose.yml`).

---

## 1. Start it

### Docker (recommended)

```bash
cp .env.example .env      # then fill in the three keys below
docker compose up --build
```

Open **http://localhost:8000** — it redirects to the console.

Set these in `.env` before starting:

| Key | Needed for | If you leave it blank |
| --- | --- | --- |
| `SECRET_KEY` | signing your login token | works, but use any long random string |
| `GITHUB_TOKEN` | GitHub API rate limit | 60 requests/hour instead of 5,000 — you will hit the limit fast |
| `OPENAI_API_KEY` | AI summaries, chat answers, overview, **and job matching** | analytics and indexing still work; AI panels stay empty. Job match needs this one — resume and JD extraction are LLM-based |

A GitHub token needs **no scopes** for public data: GitHub → Settings →
Developer settings → Personal access tokens → Fine-grained → Generate, with
"Public repositories (read-only)".

### Without Docker

You need Postgres and Redis running locally, then:

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Point `DATABASE_URL` and `REDIS_URL` in `.env` at your local services.

### If containers refuse to start

`Conflict. The container name "/analyzer_redis" is already in use` means an
older copy of the stack is still around:

```bash
docker rm -f analyzer_api analyzer_db analyzer_redis
docker compose up --build
```

---

## 2. Test every feature through the UI

Work top to bottom; each step takes under a minute.

### Check the layout first

1. Open **http://localhost:8000**. You should get a left sidebar with four
   sections, a sticky top bar showing the current page and API status, and the
   Analyze screen.
2. Narrow the window below ~900px (or open DevTools device mode). The sidebar
   collapses into a drawer behind the menu button; the layout reflows rather
   than shrinking.
3. Press <kbd>Tab</kbd> from the top: the first stop is a "Skip to content"
   link, then the navigation, then the form. Every control shows a visible
   focus ring.

### Create an account

1. Click **Sign in** (top right) → **Create account** → any username/password →
   **Create account**.
2. The dialog closes and the button reads `yourname · sign out`.

You can also skip this: click **Run analysis** straight away and the dialog
appears explaining why it is needed. Sign in there and **the analysis you asked
for starts on its own** — no need to click the button again.

*What this proves: `POST /auth/register`, JWT issued and stored.*

### 01 · Analyze a developer

1. Go to **01 Analyze**, click the `tiangolo` sample chip (or type any username).
2. Watch the run log tick through collection → analytics → AI → results.
   Cold runs take 10–40s.
3. You should see: profile header with follower counts, a 52-week commit strip
   (hover a bar for the weekly count), five score columns, language mix,
   monthly trend, résumé summary, strengths/gaps, five interview questions,
   ranked top projects, and the full repository table.
4. Re-run the same username — it returns almost instantly from the Redis cache.

*Proves: `POST /analyze`, plus `/developer`, `/score`, `/languages`,
`/activity`, `/repositories`, `/top-projects`, `/summary`, `/interview`.*

**If the AI panels are missing** the analytics still rendered — that is by
design, `POST /analyze` persists deterministic results before calling the LLM.
Check `docker compose logs api` for the AI error (usually a missing or invalid
`OPENAI_API_KEY`).

### 02 · Compare two developers

1. Go to **02 Compare**, enter two usernames, click **Compare**.
2. You should see a verdict, both scores, per-axis bars, both language mixes,
   and repository quality side by side.

*Proves: `POST /compare`.*

### 03 · Chat with a repository

1. Go to **03 Repo chat**, click the `psf/requests` chip.
2. The status pill shows **queued → indexing → ready**. Indexing a mid-sized
   repo takes 20–90s; the panel then shows file/chunk counts, source size,
   which embedder ran, and the indexed file tree.
3. The right panel fills with an AI brief — what the project does, how it works
   step by step, its components and entry points — and the suggested questions
   become specific to that repo.
4. Click a suggested question, or type your own.
5. **Then ask a follow-up that depends on the first answer** — "and where is
   that called from?", "why is it done that way?". This is the part to demo.

*Proves: `POST /repo-chat/index`, `GET /repo-chat/repos/{owner}/{repo}`,
`/overview`, `POST /repo-chat/sessions`, `/messages/stream`.*

### Check the grounding

1. In any answer, click a `[1]` chip → the cited source expands below with real
   line numbers from the real file.
2. Open the file on GitHub at those lines and confirm they match.
3. On a follow-up, look for the dashed **Searched for:** line — that is the
   rewritten standalone query the retriever actually ran.

### Sessions

1. Ask questions in one conversation, then open **03 Repo chat** for a second
   repo and back.
2. Conversations for the current repo are listed in the left panel with message
   counts; click one to reload its full transcript, citations included.
3. The **✕** deletes a conversation.

*Proves: `GET /repo-chat/sessions`, `GET .../messages`, `DELETE .../sessions/{id}`.*

### 04 · Match a candidate to a role

You need a resume PDF. Any text-based PDF works — export one from Word or
Google Docs. (A scanned image will be rejected with a clear message, which is
itself worth testing.)

1. Go to **04 Match a candidate to a role**.
2. Enter a GitHub username and a company name.
3. Paste a real job description — the fuller the better, since requirements are
   extracted from it.
4. Click **Choose PDF** and pick the resume, then **Run match**.
5. Expect, in order: the verdict dial with match % and confidence, the weighted
   calculation table, the skill ledger, discrepancies, project relevance,
   interview questions, the learning roadmap, and the disclaimer.

**The things to actually look at:**

- **The calculation table.** Score × weight = contribution, for all six
  components, summing to the headline number. Add them up by hand — they match.
- **Click any skill row.** It expands into the evidence from each source
  separately. Every line is specific enough to verify against the resume or the
  GitHub profile.
- **Find a skill the JD wants that appears nowhere.** It should read
  *"No public evidence"* with a dashed neutral border — not a red failure — and
  the rationale should call it a verification gap. Put CUDA or Kubernetes in the
  JD to force this.
- **Confidence, separately from the score.** The "Why confidence is N%" list
  itemises each penalty. More unknowns → lower confidence, not a lower score.

*Proves: `POST /job-match` (multipart), resume extraction, JD extraction,
deterministic scoring, missing-vs-unknown, discrepancy detection.*

### Job match error cases

| Try | Expected |
| --- | --- |
| Upload a `.txt` renamed to `.pdf` | 422, "That file is not a PDF" |
| Upload a scanned/image-only PDF | 422, "No text could be extracted" |
| A PDF over 2 MB | 413, size limit message |
| A two-word job description | Rejected before upload, "paste the full job description" |
| A GitHub username that doesn't exist | 404 |

### Buffered vs streamed

Uncheck **stream** next to the Ask button and ask again. Same answer, delivered
in one response instead of token by token — that is `POST .../messages` rather
than `POST .../messages/stream`.

### Error handling

| Try | Expected |
| --- | --- |
| Repo URL `https://gitlab.com/a/b` | "Not a valid GitHub repository URL" |
| A username that doesn't exist | "Check the spelling — that GitHub user doesn't exist." |
| Sign out, then run an analysis | The account dialog opens and explains why |
| Stop the API container, reload | Top bar switches to **API unreachable** |

---

## 3. Run the test suite

```bash
docker compose exec api pytest -v          # inside the container
# or, locally:
pytest -v
```

47 tests, no network and no API keys required:

- `tests/test_analyzers.py` — repository, language and activity analytics
- `tests/test_scoring.py` — project and developer score formulas
- `tests/test_job_match.py` — PDF extraction and validation, protected-attribute
  scrubbing, JD normalisation, evidence lookup, skill classification
  (missing vs unknown), deterministic scoring, discrepancy detection, project
  relevance, and the `/job-match` endpoint itself
- `tests/test_repo_chat.py` — URL parsing, file filtering, chunk line-range
  integrity, symbol detection, BM25 ranking, MMR diversification, hybrid
  search, prompt assembly

### UI tests (optional, needs Node)

```bash
npm install jsdom
node tests/ui/css-cascade.mjs            # instant, no server needed
node tests/ui/design-system.mjs          # accessibility + design tokens
python tests/ui/stub_server.py &         # stubs GitHub, OpenAI and Redis
node tests/ui/ui-flows.mjs               # 82 assertions through the real UI
```

See `tests/ui/README.md`. These need no API keys and touch no network.

---

## 4. Where things live

```
app/
  api/routes/job_match.py     POST /job-match + stored reports
  services/resume_parser.py   PDF -> text -> scrubbed -> structured
  services/jd_parser.py       JD -> categorised, weighted requirements
  services/evidence.py        where each skill is actually demonstrated
  services/match_engine.py    the deterministic scoring (no LLM in this file)
  services/job_match.py       orchestration + narration
  api/routes/repo_chat.py     the 12 chat endpoints
  services/repo_ingest.py     URL parsing, zipball → filtered files
  services/chunker.py         line-windowed chunks with symbols
  services/embeddings.py      OpenAI embedder + offline fallback
  services/vector_store.py    hybrid search + MMR
  services/repo_chat.py       indexing, condensing, answering, streaming
frontend/
  index.html                  the whole app shell
  css/app.css                 design system
  js/api.js                   API client + SSE parser
  js/charts.js                hand-drawn SVG charts
  js/views/                   one file per screen
```

The API reference is still there at **/docs** if you want to poke at endpoints
directly.
