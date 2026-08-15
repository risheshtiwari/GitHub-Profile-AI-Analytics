"""Runs the real app with GitHub, the LLM and Redis stubbed out, so the UI can
be exercised end to end without network, keys, or infrastructure."""

import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./uitest.db"
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services import ai_engine, pipeline, repo_chat, repo_ingest  # noqa: E402
from app.api.routes import repo_chat as repo_chat_routes  # noqa: E402
from app.services.github_client import GitHubClient  # noqa: E402

# ── Stub cache (no Redis) ──────────────────────────────────────────────────
_MEM: dict = {}


async def cache_get(key):
    return _MEM.get(key)


async def cache_set(key, value, ttl=None):
    _MEM[key] = json.loads(json.dumps(value, default=str))


pipeline.cache_get = cache_get
pipeline.cache_set = cache_set
repo_chat_routes.cache_get = cache_get
repo_chat_routes.cache_set = cache_set

# ── Stub GitHub ────────────────────────────────────────────────────────────
REPO_FILES = {
    "README.md": b"# Bandit Router\n\nRoutes LLM traffic across models using EXP3.\n\n## Install\n\npip install -r requirements.txt\n",
    "requirements.txt": b"fastapi\nnumpy\n",
    "app/main.py": b'from fastapi import FastAPI\nfrom app.router import BanditRouter\n\napp = FastAPI()\nrouter = BanditRouter(arms=["gpt-4o-mini", "haiku"])\n\n\n@app.post("/route")\nasync def route(prompt: str):\n    """Picks a model, calls it, then feeds the reward back to the bandit."""\n    arm = router.select_arm()\n    result = await call_model(arm, prompt)\n    router.update(arm, reward=result.quality - 0.1 * result.cost)\n    return result\n',
    "app/router.py": b'import math\nimport random\n\n\nclass BanditRouter:\n    """EXP3 over a fixed set of model arms."""\n\n    def __init__(self, arms, gamma=0.1):\n        self.arms = arms\n        self.gamma = gamma\n        self.weights = [1.0] * len(arms)\n\n    def probabilities(self):\n        total = sum(self.weights)\n        return [(1 - self.gamma) * w / total + self.gamma / len(self.arms) for w in self.weights]\n\n    def select_arm(self):\n        return random.choices(self.arms, weights=self.probabilities(), k=1)[0]\n\n    def update(self, arm, reward):\n        """Importance-weighted reward update; this is what keeps EXP3 unbiased."""\n        index = self.arms.index(arm)\n        prob = self.probabilities()[index]\n        self.weights[index] *= math.exp(self.gamma * (reward / prob) / len(self.arms))\n',
    "node_modules/junk/index.js": b"module.exports = 1;",
}


def _zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in REPO_FILES.items():
            archive.writestr(f"demo-bandit-router-abc123/{path}", content)
    return buffer.getvalue()


def _iso(days_ago):
    return (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


FAKE_REPOS = [
    {"name": "bandit-router", "full_name": "demo/bandit-router", "stargazers_count": 412,
     "forks_count": 38, "open_issues_count": 4, "language": "Python", "archived": False,
     "license": {"key": "mit"}, "size": 2400, "topics": ["bandits", "llm", "pytest"],
     "pushed_at": _iso(3), "created_at": _iso(700)},
    {"name": "aes-fpga", "full_name": "demo/aes-fpga", "stargazers_count": 96,
     "forks_count": 11, "open_issues_count": 1, "language": "Verilog", "archived": False,
     "license": None, "size": 900, "topics": ["fpga", "crypto"],
     "pushed_at": _iso(40), "created_at": _iso(500)},
    {"name": "bot-detection", "full_name": "demo/bot-detection", "stargazers_count": 27,
     "forks_count": 3, "open_issues_count": 0, "language": "Python", "archived": True,
     "license": {"key": "apache-2.0"}, "size": 1500, "topics": ["ml", "ci"],
     "pushed_at": _iso(210), "created_at": _iso(620)},
]

LANGS = {
    "demo/bandit-router": {"Python": 82000, "Shell": 4000},
    "demo/aes-fpga": {"Verilog": 40000, "Python": 6000},
    "demo/bot-detection": {"Python": 31000, "HTML": 9000, "CSS": 3000},
}


class FakeGitHubClient(GitHubClient):
    def __init__(self, token=None):
        self.token = token

    async def close(self):
        pass

    async def get_user(self, username):
        return {"login": username, "name": username.title(), "bio": "Backend + ML systems.",
                "avatar_url": "", "followers": 1280, "following": 42, "public_repos": len(FAKE_REPOS)}

    async def get_repos(self, username, max_repos=None):
        return FAKE_REPOS

    async def get_languages(self, full_name):
        return LANGS.get(full_name, {"Python": 1000})

    async def get_repo_languages(self, owner, repo):
        return {"Python": 82000, "Markdown": 2400}

    async def has_readme(self, full_name):
        return full_name != "demo/aes-fpga"

    async def get_weekly_commit_activity(self, full_name):
        base = int((datetime.utcnow() - timedelta(weeks=52)).timestamp())
        counts = [0, 3, 7, 12, 4, 0, 0, 9, 14, 21, 6, 2, 8, 11, 3, 0, 5, 17, 22, 9, 4, 1,
                  0, 6, 13, 19, 7, 3, 10, 15, 2, 0, 0, 8, 12, 5, 18, 24, 9, 3, 6, 11, 14,
                  2, 0, 7, 16, 20, 8, 4, 9, 13]
        return [{"week": base + i * 604800, "total": c, "days": [c // 7] * 7}
                for i, c in enumerate(counts)]

    async def get_repo(self, owner, repo):
        return {"default_branch": "main", "description": "Routes LLM traffic across models using EXP3.",
                "homepage": "", "stargazers_count": 412, "forks_count": 38,
                "topics": ["bandits", "llm"], "language": "Python"}

    async def download_zipball(self, owner, repo, ref="HEAD"):
        return _zip_bytes()


pipeline.GitHubClient = FakeGitHubClient
repo_chat.GitHubClient = FakeGitHubClient
repo_ingest.GitHubClient = FakeGitHubClient


async def fake_fetch_snapshot(ref, client=None):
    fake = FakeGitHubClient()
    metadata = await fake.get_repo(ref.owner, ref.repo)
    snapshot = repo_ingest.extract_files_from_zip(
        _zip_bytes(), repo_ingest.RepoRef(ref.owner, ref.repo, "main"))
    return metadata, snapshot


repo_chat.repo_ingest.fetch_repo_snapshot = fake_fetch_snapshot


# ── Stub LLM ───────────────────────────────────────────────────────────────
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Delta:
    def __init__(self, content):
        self.content = content


class _StreamChoice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _StreamPart:
    def __init__(self, content):
        self.choices = [_StreamChoice(content)]


class _Stream:
    def __init__(self, text):
        self.chunks = [text[i:i + 12] for i in range(0, len(text), 12)]

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self.chunks):
            raise StopAsyncIteration
        part = _StreamPart(self.chunks[self._i])
        self._i += 1
        return part


class FakeCompletions:
    @staticmethod
    async def create(**kwargs):
        system = kwargs["messages"][0]["content"]
        stream = kwargs.get("stream", False)

        if "standalone search query" in system:
            return _Resp('{"query": "EXP3 importance weighted reward update BanditRouter"}')
        if "senior technical recruiter" in system:
            return _Resp(json.dumps({
                "strengths": ["Deep bandit/online-learning expertise", "Ships working FPGA and ML systems",
                              "Consistent multi-year commit cadence"],
                "weaknesses": ["Limited frontend surface area", "Few repos carry a LICENSE"],
                "likely_expertise": ["Online learning", "Python backends", "Digital design"],
                "suggested_learning": ["Distributed systems", "TypeScript for full-stack range"],
            }))
        if "resume/LinkedIn summaries" in system:
            return _Resp("Backend and ML systems engineer with deep grounding in online learning, "
                         "shipping bandit-based routing infrastructure and hardware crypto cores. "
                         "Consistent open-source contributor across Python and Verilog.")
        if "interview questions" in system:
            return _Resp(json.dumps({"questions": [
                "Why does EXP3 need importance weighting for its reward estimates?",
                "How would you bound regret when the arm set changes over time?",
                "Walk me through the pipeline stages in your AES-128 core.",
                "How did you validate the FPGA implementation against FIPS 197?",
                "What breaks first if your router's reward signal is delayed?",
            ]}))
        if "staff engineer writing an onboarding brief" in system:
            return _Resp(json.dumps({
                "what_it_does": "A FastAPI service that routes each incoming prompt to one of several "
                                "LLM backends, learning which model gives the best quality-per-cost "
                                "using an EXP3 adversarial bandit.",
                "how_it_works": [
                    "A request hits POST /route with a prompt.",
                    "BanditRouter.select_arm samples a model from the current weight distribution.",
                    "The chosen model is called and returns quality and cost.",
                    "BanditRouter.update applies an importance-weighted exponential update.",
                ],
                "architecture": [
                    {"component": "FastAPI app", "responsibility": "HTTP surface for routing requests", "path": "app/main.py"},
                    {"component": "BanditRouter", "responsibility": "EXP3 arm selection and weight updates", "path": "app/router.py"},
                ],
                "tech_stack": ["Python", "FastAPI", "NumPy"],
                "entry_points": ["app/main.py", "app/router.py"],
                "notable_patterns": ["Importance weighting keeps reward estimates unbiased"],
                "suggested_questions": [
                    "How does the exploration rate gamma affect routing?",
                    "Where is the reward actually computed?",
                    "What happens if a model call fails mid-request?",
                    "How would I add a fourth model arm?",
                    "Is the weight state persisted anywhere?",
                ],
            }))

        answer = ("This service routes each prompt to one of several LLM backends and learns which "
                  "one performs best. The HTTP entry point is `POST /route` [1], which asks the "
                  "router to pick an arm, calls that model, then feeds a reward back.\n\n"
                  "The learning itself is EXP3 [2]. `select_arm` samples from a distribution that "
                  "mixes the learned weights with a uniform floor set by gamma, and `update` applies "
                  "an importance-weighted exponential update — dividing the observed reward by the "
                  "probability of having picked that arm is what keeps the estimate unbiased [2].")
        if stream:
            return _Stream(answer)
        return _Resp(answer)


class FakeChat:
    completions = FakeCompletions


class FakeLLM:
    chat = FakeChat


ai_engine.get_client = lambda: FakeLLM

if os.path.exists("uitest.db"):
    os.remove("uitest.db")

from app.main import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8111, log_level="warning")
