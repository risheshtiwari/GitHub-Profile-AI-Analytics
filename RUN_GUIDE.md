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
| `OPENAI_API_KEY` | AI summaries, chat answers, overview | analytics and indexing still work; AI panels stay empty |

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
- `tests/test_repo_chat.py` — URL parsing, file filtering, chunk line-range
  integrity, symbol detection, BM25 ranking, MMR diversification, hybrid
  search, prompt assembly

### UI tests (optional, needs Node)

```bash
npm install jsdom
node tests/ui/css-cascade.mjs            # instant, no server needed
python tests/ui/stub_server.py &         # stubs GitHub, OpenAI and Redis
node tests/ui/ui-flows.mjs               # 58 assertions through the real UI
```

See `tests/ui/README.md`. These need no API keys and touch no network.

---

## 4. Where things live

```
app/
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
