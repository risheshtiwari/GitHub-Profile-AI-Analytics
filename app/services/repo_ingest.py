"""Repo Chat — Stage 1: ingestion.

Turns a GitHub repository URL into a filtered set of source files plus a
structural summary (file tree, README excerpt, dependency manifests).

Everything here is deliberately network-free except `fetch_repo_snapshot`:
`parse_repo_url` and `extract_files_from_zip` are pure functions so they can be
unit tested against a synthetic in-memory zip with no GitHub calls.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services.github_client import GitHubClient, GitHubNotFoundError

settings = get_settings()


class InvalidRepoUrlError(ValueError):
    pass


class RepoNotFoundError(Exception):
    pass


class EmptyRepoError(Exception):
    """Repo cloned fine but contained no ingestible source files."""


# --------------------------------------------------------------------------- #
# URL parsing
# --------------------------------------------------------------------------- #

_URL_PATTERNS = [
    # https://github.com/owner/repo(/tree/ref/...)?(.git)?
    re.compile(r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?"
               r"(?:/(?:tree|blob)/(?P<ref>[\w.\-/]+?))?/?$"),
    # git@github.com:owner/repo.git
    re.compile(r"^git@github\.com:(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"),
    # bare "owner/repo" shorthand
    re.compile(r"^(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"),
]


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    ref: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_repo_url(url: str) -> RepoRef:
    """Accepts any of:
        https://github.com/psf/requests
        https://github.com/psf/requests.git
        https://github.com/psf/requests/tree/main
        git@github.com:psf/requests.git
        psf/requests
    """
    candidate = (url or "").strip()
    if not candidate:
        raise InvalidRepoUrlError("Repository URL is empty")

    for pattern in _URL_PATTERNS:
        match = pattern.match(candidate)
        if match:
            owner = match.group("owner")
            repo = match.group("repo")
            ref = match.groupdict().get("ref")
            if owner in {".", ".."} or repo in {".", ".."}:
                raise InvalidRepoUrlError(f"Not a valid GitHub repository URL: {url}")
            return RepoRef(owner=owner, repo=repo, ref=ref or None)

    raise InvalidRepoUrlError(f"Not a valid GitHub repository URL: {url}")


# --------------------------------------------------------------------------- #
# File filtering
# --------------------------------------------------------------------------- #

SKIP_DIRS = {
    ".git", ".github/workflows/cache", "node_modules", "vendor", "dist", "build",
    "out", "target", "__pycache__", ".venv", "venv", "env", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", ".idea", ".vscode", "coverage",
    "site-packages", "bower_components", ".terraform", "Pods", ".gradle",
}

SKIP_FILE_PATTERNS = [
    re.compile(r"\.min\.(js|css)$"),
    re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|Gemfile\.lock|composer\.lock)$"),
    re.compile(r"\.(lock|map|snap)$"),
    re.compile(r"(^|/)\.DS_Store$"),
    re.compile(r"_pb2(_grpc)?\.py$"),
    re.compile(r"\.generated\.[\w]+$"),
]

# extension -> language label
CODE_EXTENSIONS = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#", ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".sql": "SQL", ".r": "R", ".jl": "Julia", ".lua": "Lua", ".dart": "Dart",
    ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell",
    ".vue": "Vue", ".svelte": "Svelte", ".v": "Verilog", ".sv": "SystemVerilog",
    ".vhd": "VHDL", ".proto": "Protobuf", ".tf": "Terraform", ".sol": "Solidity",
}

DOC_EXTENSIONS = {".md": "Markdown", ".rst": "reStructuredText", ".txt": "Text", ".adoc": "AsciiDoc"}

CONFIG_EXTENSIONS = {
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".ini": "INI",
    ".cfg": "INI", ".json": "JSON", ".env": "Env", ".gradle": "Gradle",
}

# Files that describe *how the project is built/run* — always worth ingesting.
MANIFEST_FILES = {
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
    "package.json", "tsconfig.json", "go.mod", "Cargo.toml", "pom.xml",
    "build.gradle", "Gemfile", "composer.json", "Dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "Makefile", "Procfile", ".env.example", "alembic.ini",
}

# Ingestion priority — lower sorts first, so the budget is spent on signal.
_PRIORITY = {"readme": 0, "manifest": 1, "code": 2, "doc": 3, "config": 4}


@dataclass
class RepoFile:
    path: str
    content: str
    language: str
    category: str
    size_bytes: int

    @property
    def line_count(self) -> int:
        return self.content.count("\n") + 1


@dataclass
class RepoSnapshot:
    ref: RepoRef
    files: list[RepoFile] = field(default_factory=list)
    file_tree: list[str] = field(default_factory=list)
    readme_excerpt: str = ""
    manifest_summary: dict = field(default_factory=dict)
    total_bytes: int = 0
    skipped_files: int = 0


def _strip_archive_root(name: str) -> str:
    """GitHub zipballs nest everything under `owner-repo-<sha>/`."""
    parts = name.split("/", 1)
    return parts[1] if len(parts) == 2 else name


def _is_skipped_path(path: str) -> bool:
    parts = path.split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    if any(part.startswith(".") and part not in {".github", ".env.example"} for part in parts[:-1]):
        return True
    return any(pattern.search(path) for pattern in SKIP_FILE_PATTERNS)


def classify_file(path: str) -> tuple[str, str] | None:
    """Returns (language, category) or None if the file should be skipped."""
    filename = path.split("/")[-1]
    lower = filename.lower()
    dot = filename.rfind(".")
    ext = filename[dot:].lower() if dot > 0 else ""

    if lower.startswith("readme"):
        return DOC_EXTENSIONS.get(ext, "Markdown"), "readme"
    if filename in MANIFEST_FILES or lower.startswith("dockerfile"):
        return CONFIG_EXTENSIONS.get(ext, "Config"), "manifest"
    if ext in CODE_EXTENSIONS:
        return CODE_EXTENSIONS[ext], "code"
    if ext in DOC_EXTENSIONS:
        return DOC_EXTENSIONS[ext], "doc"
    if ext in CONFIG_EXTENSIONS:
        return CONFIG_EXTENSIONS[ext], "config"
    return None


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:2048]


def _decode(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _summarise_tree(paths: list[str], limit: int = 120) -> list[str]:
    """Compact directory listing: every directory, plus files up to `limit`."""
    dirs: dict[str, int] = {}
    for path in paths:
        directory = path.rsplit("/", 1)[0] if "/" in path else "."
        dirs[directory] = dirs.get(directory, 0) + 1

    lines: list[str] = []
    for directory in sorted(dirs):
        lines.append(f"{directory}/ ({dirs[directory]} files)")
    for path in sorted(paths)[:limit]:
        lines.append(path)
    return lines


def extract_files_from_zip(zip_bytes: bytes, ref: RepoRef) -> RepoSnapshot:
    """Pure function: zip archive -> filtered, budgeted RepoSnapshot."""
    snapshot = RepoSnapshot(ref=ref)
    all_paths: list[str] = []
    candidates: list[tuple[int, str, bytes]] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = _strip_archive_root(info.filename)
            if not path:
                continue
            all_paths.append(path)

            if _is_skipped_path(path):
                snapshot.skipped_files += 1
                continue
            classification = classify_file(path)
            if classification is None:
                snapshot.skipped_files += 1
                continue
            if info.file_size > settings.ingest_max_file_bytes:
                snapshot.skipped_files += 1
                continue

            _language, category = classification
            candidates.append((_PRIORITY[category], path, archive.read(info)))

        # Spend the ingestion budget on the highest-signal files first.
        candidates.sort(key=lambda item: (item[0], item[1]))

        for _priority, path, raw in candidates:
            if len(snapshot.files) >= settings.ingest_max_files:
                snapshot.skipped_files += 1
                continue
            if snapshot.total_bytes >= settings.ingest_max_total_bytes:
                snapshot.skipped_files += 1
                continue
            if _looks_binary(raw):
                snapshot.skipped_files += 1
                continue
            text = _decode(raw)
            if text is None or not text.strip():
                snapshot.skipped_files += 1
                continue

            language, category = classify_file(path)  # type: ignore[misc]
            snapshot.files.append(
                RepoFile(
                    path=path,
                    content=text,
                    language=language,
                    category=category,
                    size_bytes=len(raw),
                )
            )
            snapshot.total_bytes += len(raw)

            if category == "readme" and not snapshot.readme_excerpt and "/" not in path:
                snapshot.readme_excerpt = text[:4000]
            if category == "manifest":
                snapshot.manifest_summary[path] = text[:1500]

    snapshot.file_tree = _summarise_tree(
        [f for f in all_paths if not _is_skipped_path(f)]
    )

    if not snapshot.files:
        raise EmptyRepoError(ref.full_name)
    return snapshot


async def fetch_repo_snapshot(ref: RepoRef, client: GitHubClient | None = None) -> tuple[dict, RepoSnapshot]:
    """Fetches repo metadata + a source snapshot. Returns (metadata, snapshot)."""
    owned_client = client is None
    client = client or GitHubClient()
    try:
        try:
            metadata = await client.get_repo(ref.owner, ref.repo)
        except GitHubNotFoundError:
            raise RepoNotFoundError(ref.full_name)

        resolved_ref = ref.ref or metadata.get("default_branch") or "HEAD"
        try:
            zip_bytes = await client.download_zipball(ref.owner, ref.repo, resolved_ref)
        except GitHubNotFoundError:
            raise RepoNotFoundError(f"{ref.full_name}@{resolved_ref}")

        snapshot = extract_files_from_zip(zip_bytes, RepoRef(ref.owner, ref.repo, resolved_ref))
        return metadata, snapshot
    finally:
        if owned_client:
            await client.close()
