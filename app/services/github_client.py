"""Async GitHub REST API client with pagination, auth, and rate-limit-aware retries."""

from datetime import datetime

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings

settings = get_settings()

GITHUB_API = "https://api.github.com"


class GitHubNotFoundError(Exception):
    pass


class GitHubRateLimitError(Exception):
    pass


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = token or settings.github_token
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.AsyncClient(base_url=GITHUB_API, headers=headers, timeout=20.0)

    async def close(self):
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(GitHubRateLimitError),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
    )
    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        resp = await self._client.get(path, params=params)
        if resp.status_code == 404:
            raise GitHubNotFoundError(path)
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubRateLimitError("GitHub API rate limit exceeded")
        resp.raise_for_status()
        return resp

    async def get_user(self, username: str) -> dict:
        resp = await self._get(f"/users/{username}")
        return resp.json()

    async def get_repos(self, username: str, max_repos: int | None = None) -> list[dict]:
        """Paginated fetch of all public repos, sorted by stars (most impressive first)."""
        max_repos = max_repos or settings.max_repos_analyzed
        repos: list[dict] = []
        page = 1
        while len(repos) < max_repos:
            resp = await self._get(
                f"/users/{username}/repos",
                params={"per_page": 100, "page": page, "sort": "pushed", "type": "owner"},
            )
            batch = resp.json()
            if not batch:
                break
            repos.extend(batch)
            page += 1
            if len(batch) < 100:
                break
        repos.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)
        return repos[:max_repos]

    async def get_languages(self, full_name: str) -> dict[str, int]:
        try:
            resp = await self._get(f"/repos/{full_name}/languages")
            return resp.json()
        except GitHubNotFoundError:
            return {}

    async def has_readme(self, full_name: str) -> bool:
        try:
            await self._get(f"/repos/{full_name}/readme")
            return True
        except GitHubNotFoundError:
            return False

    async def get_weekly_commit_activity(self, full_name: str) -> list[dict]:
        """Returns up to 52 weeks of commit activity: [{week, total, days:[7 ints]}]."""
        try:
            resp = await self._get(f"/repos/{full_name}/stats/commit_activity")
            data = resp.json()
            return data if isinstance(data, list) else []
        except GitHubNotFoundError:
            return []

    @staticmethod
    def parse_gh_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
