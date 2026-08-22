"""Tests for the Repo Chat pipeline.

No network and no LLM: ingestion is tested against a synthetic in-memory zip,
and retrieval against the deterministic HashingEmbedder. That keeps the whole
suite free and repeatable.
"""

import io
import zipfile

import pytest

from app.services import chunker, repo_ingest, vector_store
from app.services.embeddings import HashingEmbedder, tokenize
from app.services.repo_ingest import (
    InvalidRepoUrlError,
    RepoRef,
    extract_files_from_zip,
    parse_repo_url,
)

# --------------------------------------------------------------------------- #
# URL parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,owner,repo,ref",
    [
        ("https://github.com/psf/requests", "psf", "requests", None),
        ("https://github.com/psf/requests.git", "psf", "requests", None),
        ("http://www.github.com/psf/requests/", "psf", "requests", None),
        ("https://github.com/psf/requests/tree/main", "psf", "requests", "main"),
        ("git@github.com:psf/requests.git", "psf", "requests", None),
        ("psf/requests", "psf", "requests", None),
        ("https://github.com/manoj5130/GitHub-Analyzer", "manoj5130", "GitHub-Analyzer", None),
    ],
)
def test_parse_repo_url_variants(url, owner, repo, ref):
    parsed = parse_repo_url(url)
    assert (parsed.owner, parsed.repo, parsed.ref) == (owner, repo, ref)


@pytest.mark.parametrize("url", ["", "   ", "https://gitlab.com/a/b", "not a url at all", "https://github.com/onlyowner"])
def test_parse_repo_url_rejects_invalid(url):
    with pytest.raises(InvalidRepoUrlError):
        parse_repo_url(url)


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #

SAMPLE_MAIN = '''"""Entry point."""
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
'''

SAMPLE_SCORING = """def project_score(repo, max_stars, max_forks, activity):
    return 0.4 * repo["stars"] / max_stars + 0.2 * activity


def composite_developer_score(consistency, popularity):
    return round(0.5 * consistency + 0.5 * popularity, 2)
"""


def _build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(f"owner-repo-abc123/{path}", content)
    return buffer.getvalue()


@pytest.fixture
def sample_zip() -> bytes:
    return _build_zip(
        {
            "README.md": b"# Demo\n\nA demo service.\n\n## Usage\n\nRun it with uvicorn.\n",
            "requirements.txt": b"fastapi\nuvicorn\n",
            "app/main.py": SAMPLE_MAIN.encode(),
            "app/services/scoring.py": SAMPLE_SCORING.encode(),
            "node_modules/left-pad/index.js": b"module.exports = function(){}",
            "dist/bundle.min.js": b"var a=1;",
            "package-lock.json": b"{}",
            "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
            ".git/config": b"[core]",
        }
    )


def test_extract_filters_noise_and_keeps_source(sample_zip):
    snapshot = extract_files_from_zip(sample_zip, RepoRef("owner", "repo", "main"))
    paths = {file.path for file in snapshot.files}

    assert "app/main.py" in paths
    assert "app/services/scoring.py" in paths
    assert "README.md" in paths
    assert "requirements.txt" in paths

    assert not any(p.startswith("node_modules/") for p in paths)
    assert "dist/bundle.min.js" not in paths
    assert "package-lock.json" not in paths
    assert "assets/logo.png" not in paths
    assert ".git/config" not in paths
    assert snapshot.skipped_files > 0


def test_extract_captures_structural_context(sample_zip):
    snapshot = extract_files_from_zip(sample_zip, RepoRef("owner", "repo", "main"))
    assert snapshot.readme_excerpt.startswith("# Demo")
    assert "requirements.txt" in snapshot.manifest_summary
    assert any("app/services" in line for line in snapshot.file_tree)
    assert snapshot.total_bytes > 0


def test_extract_raises_on_repo_with_no_source():
    empty = _build_zip({"assets/logo.png": b"\x89PNG\r\n\x1a\n\x00binary"})
    with pytest.raises(repo_ingest.EmptyRepoError):
        extract_files_from_zip(empty, RepoRef("owner", "repo"))


def test_classify_file():
    assert repo_ingest.classify_file("app/main.py") == ("Python", "code")
    assert repo_ingest.classify_file("README.md")[1] == "readme"
    assert repo_ingest.classify_file("Dockerfile")[1] == "manifest"
    assert repo_ingest.classify_file("logo.png") is None


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def test_chunk_preserves_line_ranges_and_covers_file():
    content = "\n".join(f"line_{i}" for i in range(1, 201))
    chunks = chunker.chunk_file("a.py", content, "Python", target_lines=50, overlap_lines=10)

    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 200
    for chunk in chunks:
        assert chunk.start_line <= chunk.end_line
        assert chunk.end_line <= 200


def test_chunk_windows_overlap():
    content = "\n".join(f"line_{i}" for i in range(1, 121))
    chunks = chunker.chunk_file("a.py", content, "Python", target_lines=50, overlap_lines=10)
    assert len(chunks) > 1
    assert chunks[1].start_line < chunks[0].end_line  # overlap keeps context across the seam


def test_chunk_detects_enclosing_symbol():
    chunks = chunker.chunk_file("scoring.py", SAMPLE_SCORING, "Python", target_lines=4, overlap_lines=0)
    symbols = [chunk.symbol for chunk in chunks if chunk.symbol]
    assert any("def project_score" in symbol for symbol in symbols)


def test_embedding_text_includes_path_and_lines():
    chunk = chunker.chunk_file("app/main.py", SAMPLE_MAIN, "Python")[0]
    text = chunk.embedding_text()
    assert "app/main.py" in text
    assert "Lines 1-" in text


def test_markdown_chunks_split_on_headings():
    markdown = "# Title\n\nintro\n\n## Install\n\npip install x\n\n## Usage\n\nrun it\n"
    chunks = chunker.chunk_file("README.md", markdown, "Markdown")
    symbols = [chunk.symbol for chunk in chunks]
    assert "Install" in symbols and "Usage" in symbols


def test_chunk_files_respects_budget():
    class FakeFile:
        def __init__(self, path, content, language):
            self.path, self.content, self.language = path, content, language

    files = [FakeFile(f"f{i}.py", "\n".join(["x = 1"] * 300), "Python") for i in range(10)]
    chunks, coverage = chunker.chunk_files(files, max_chunks=25)
    assert len(chunks) == 25


def test_chunk_budget_truncation_is_reported_not_silent():
    """Silent truncation makes the assistant confidently wrong about files it
    never saw. The caller must be able to tell that coverage is incomplete."""
    class FakeFile:
        def __init__(self, path, content, language):
            self.path, self.content, self.language = path, content, language

    files = [FakeFile(f"f{i}.py", "\n".join(["x = 1"] * 300), "Python") for i in range(10)]
    _chunks, coverage = chunker.chunk_files(files, max_chunks=25)

    assert coverage["budget_reached"] is True
    assert coverage["files_not_indexed"]                 # names the excluded files
    assert coverage["chunk_budget"] == 25


def test_no_truncation_report_when_everything_fits():
    class FakeFile:
        def __init__(self, path, content, language):
            self.path, self.content, self.language = path, content, language

    files = [FakeFile("small.py", "x = 1\ny = 2", "Python")]
    _chunks, coverage = chunker.chunk_files(files, max_chunks=100)

    assert coverage["budget_reached"] is False
    assert coverage["files_not_indexed"] == []
    assert coverage["files_partially_indexed"] == []


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


def test_tokenize_splits_identifiers():
    tokens = tokenize("composite_developer_score(consistency)")
    assert "composite_developer_score" in tokens
    assert "developer" in tokens and "score" in tokens


def test_tokenize_splits_camel_case():
    assert "check" in tokenize("healthCheckHandler")


def test_cosine_similarity_bounds():
    assert vector_store.cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert vector_store.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert vector_store.cosine_similarity([1, 0], []) == 0.0


def test_bm25_ranks_matching_document_first():
    docs = [tokenize("rate limit retry backoff github client"), tokenize("pie chart colors frontend")]
    scores = vector_store.BM25Index(docs).scores(tokenize("rate limit backoff"))
    assert scores[0] > scores[1]


def test_mmr_diversifies_over_near_duplicates():
    matrix = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]
    candidates = [
        vector_store.ScoredChunk(0, 0.90, 0.9, 0.9),
        vector_store.ScoredChunk(1, 0.89, 0.9, 0.9),
        vector_store.ScoredChunk(2, 0.60, 0.6, 0.6),
    ]
    picked = vector_store.mmr_rerank(candidates, matrix, top_k=2, diversity=0.5)
    # The near-duplicate of #0 should lose to the genuinely different chunk.
    assert [chunk.index for chunk in picked] == [0, 2]


@pytest.mark.asyncio
async def test_hybrid_search_finds_the_right_chunk():
    embedder = HashingEmbedder(dimensions=256)
    corpus = [
        "File: app/services/github_client.py | Symbol: def download_zipball\n"
        "async def download_zipball(self, owner, repo, ref): resp = await self._client.get(...)",
        "File: app/services/language_analyzer.py | Symbol: def language_diversity_score\n"
        "def language_diversity_score(totals): return shannon entropy of language bytes",
        "File: README.md | Symbol: Install\npip install -r requirements.txt then docker compose up",
    ]
    matrix = await embedder.embed_documents(corpus)
    token_docs = [tokenize(text) for text in corpus]

    query = "how does it download the repository archive"
    hits = vector_store.search(
        query_vector=await embedder.embed_query(query),
        query_text=query,
        matrix=matrix,
        token_docs=token_docs,
        top_k=2,
    )
    assert hits[0].index == 0


@pytest.mark.asyncio
async def test_hashing_embedder_is_deterministic_and_normalised():
    embedder = HashingEmbedder(dimensions=128)
    first = await embedder.embed_query("developer score")
    second = await embedder.embed_query("developer score")
    assert first == second
    assert len(first) == 128
    assert sum(value * value for value in first) == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #


def test_context_block_is_numbered_and_cites_lines():
    from app.services.repo_chat import build_context_block

    block = build_context_block(
        [
            {"path": "app/main.py", "start_line": 1, "end_line": 12, "symbol": "def health_check",
             "language": "Python", "content": "async def health_check(): ..."},
        ]
    )
    assert "[1] app/main.py:1-12" in block
    assert "def health_check" in block


def test_repo_card_includes_tree_and_languages():
    from app.services.repo_chat import build_repo_card

    class FakeRepo:
        full_name = "owner/repo"
        ref = "main"
        default_branch = "main"
        description = "A demo service"
        topics = ["fastapi"]
        languages = {"Python": 900, "HTML": 100}
        stars = 12
        forks = 3
        file_count = 4
        file_tree = ["app/", "app/main.py"]
        readme_excerpt = "# Demo"
        manifest_summary = {"requirements.txt": "fastapi"}

    card = build_repo_card(FakeRepo())
    assert "owner/repo" in card
    assert "Python 90%" in card
    assert "app/main.py" in card
