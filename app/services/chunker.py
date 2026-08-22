"""Repo Chat — Stage 2: chunking.

Splits source files into retrievable slices. Two things matter for answer
quality here:

1. **Line ranges are preserved**, so every answer can cite `path:start-end`
   and the user can verify it against the real file.
2. **Each chunk carries its enclosing symbol** (nearest preceding def/class/
   function header) and its file path, prepended as a header line before
   embedding. A bare 40-line slice of a function body is nearly unsearchable;
   the same slice labelled `app/services/scoring.py :: def composite_developer_score`
   matches a natural-language question far better.

Pure functions — no network, no DB, fully unit testable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.core.config import get_settings

settings = get_settings()

# Nearest-enclosing-symbol detection, per language family.
_SYMBOL_PATTERNS: dict[str, list[re.Pattern]] = {
    "Python": [re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)")],
    "JavaScript": [
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\("),
        re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"),
    ],
    "Java": [re.compile(r"^\s*(?:public|private|protected).*?\s(\w+)\s*\("),
             re.compile(r"^\s*(?:public\s+)?(?:abstract\s+)?class\s+(\w+)")],
    "Go": [re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)"), re.compile(r"^\s*type\s+(\w+)\s+struct")],
    "Rust": [re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
             re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait|impl)\s+(\w+)")],
    "Ruby": [re.compile(r"^\s*(?:def|class|module)\s+([\w.]+)")],
    "C": [re.compile(r"^[\w*\s]+?(\w+)\s*\([^;]*\)\s*\{")],
}
_SYMBOL_PATTERNS["TypeScript"] = _SYMBOL_PATTERNS["JavaScript"]
_SYMBOL_PATTERNS["Vue"] = _SYMBOL_PATTERNS["JavaScript"]
_SYMBOL_PATTERNS["Svelte"] = _SYMBOL_PATTERNS["JavaScript"]
_SYMBOL_PATTERNS["Kotlin"] = _SYMBOL_PATTERNS["Java"]
_SYMBOL_PATTERNS["C#"] = _SYMBOL_PATTERNS["Java"]
_SYMBOL_PATTERNS["C++"] = _SYMBOL_PATTERNS["C"]

_MD_HEADING = re.compile(r"^(#{1,4})\s+(.*)")


@dataclass
class Chunk:
    path: str
    language: str
    content: str
    start_line: int
    end_line: int
    symbol: str | None = None

    @property
    def token_estimate(self) -> int:
        # ~4 chars/token is close enough for budgeting; avoids a tiktoken dependency.
        return max(1, len(self.content) // 4)

    def embedding_text(self) -> str:
        """What actually gets embedded — path + symbol context, then the code."""
        header = f"File: {self.path}"
        if self.symbol:
            header += f" | Symbol: {self.symbol}"
        header += f" | Lines {self.start_line}-{self.end_line}"
        return f"{header}\n{self.content}"


def _detect_symbol(lines: list[str], upto: int, language: str) -> str | None:
    """Nearest symbol declaration at or above `upto` (0-indexed, inclusive)."""
    patterns = _SYMBOL_PATTERNS.get(language)
    if not patterns:
        return None
    for index in range(min(upto, len(lines) - 1), -1, -1):
        line = lines[index]
        for pattern in patterns:
            match = pattern.match(line)
            if match:
                return match.group(0).strip().rstrip("{:").strip()
    return None


def _split_lines_windowed(
    path: str,
    language: str,
    lines: list[str],
    target: int,
    overlap: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not lines:
        return chunks

    step = max(1, target - overlap)
    start = 0
    while start < len(lines):
        end = min(start + target, len(lines))
        body = "\n".join(lines[start:end])
        if body.strip():
            chunks.append(
                Chunk(
                    path=path,
                    language=language,
                    content=body,
                    start_line=start + 1,
                    end_line=end,
                    symbol=_detect_symbol(lines, start, language),
                )
            )
        if end >= len(lines):
            break
        start += step
    return chunks


def _chunk_markdown(path: str, language: str, text: str, target: int) -> list[Chunk]:
    """Markdown splits on headings — sections are the natural retrieval unit."""
    lines = text.split("\n")
    sections: list[tuple[int, int]] = []
    current_start = 0
    for index, line in enumerate(lines):
        if _MD_HEADING.match(line) and index > current_start:
            sections.append((current_start, index))
            current_start = index
    sections.append((current_start, len(lines)))

    chunks: list[Chunk] = []
    for start, end in sections:
        if end - start > target * 2:  # oversized section — window it
            windowed = _split_lines_windowed(
                path, language, lines[start:end], target, settings.chunk_overlap_lines
            )
            for chunk in windowed:  # shift back to absolute file line numbers
                chunk.start_line += start
                chunk.end_line += start
            chunks.extend(windowed)
            continue
        body = "\n".join(lines[start:end])
        if not body.strip():
            continue
        heading = _MD_HEADING.match(lines[start])
        chunks.append(
            Chunk(
                path=path,
                language=language,
                content=body,
                start_line=start + 1,
                end_line=end,
                symbol=heading.group(2).strip() if heading else None,
            )
        )
    return chunks


def _notebook_to_text(text: str) -> str:
    """Flatten a .ipynb into readable source so notebooks are searchable too."""
    try:
        notebook = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    parts: list[str] = []
    for index, cell in enumerate(notebook.get("cells", [])):
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue
        kind = cell.get("cell_type", "code")
        parts.append(f"# --- cell {index} ({kind}) ---\n{source}")
    return "\n\n".join(parts) or text


def chunk_file(
    path: str,
    content: str,
    language: str,
    target_lines: int | None = None,
    overlap_lines: int | None = None,
) -> list[Chunk]:
    target = target_lines or settings.chunk_target_lines
    overlap = overlap_lines if overlap_lines is not None else settings.chunk_overlap_lines
    overlap = min(overlap, max(0, target - 1))

    if path.endswith(".ipynb"):
        content = _notebook_to_text(content)
        language = "Python"

    if language in {"Markdown", "reStructuredText", "AsciiDoc"}:
        return _chunk_markdown(path, language, content, target)

    return _split_lines_windowed(path, language, content.split("\n"), target, overlap)


def chunk_files(files, max_chunks: int | None = None) -> tuple[list[Chunk], dict]:
    """Chunks an iterable of RepoFile, respecting the global chunk budget.

    Returns the chunks *and* a coverage report. Truncation used to be silent,
    which is the worst way to lose accuracy: the assistant would confidently
    answer "that isn't in this repository" about a file that simply never got
    indexed. Files are ingested in priority order (README, manifests, then
    code), so what gets dropped is the least important — but the user still
    needs to be told it happened.
    """
    budget = max_chunks or settings.ingest_max_chunks
    chunks: list[Chunk] = []
    files_indexed: list[str] = []
    files_truncated: list[str] = []
    files_skipped: list[str] = []

    for file in files:
        if len(chunks) >= budget:
            files_skipped.append(file.path)
            continue

        file_chunks = chunk_file(file.path, file.content, file.language)
        room = budget - len(chunks)
        if len(file_chunks) > room:
            chunks.extend(file_chunks[:room])
            files_truncated.append(file.path)
        else:
            chunks.extend(file_chunks)
            files_indexed.append(file.path)

    coverage = {
        "chunk_budget": budget,
        "budget_reached": len(chunks) >= budget,
        "files_fully_indexed": len(files_indexed),
        "files_partially_indexed": files_truncated,
        "files_not_indexed": files_skipped,
    }
    return chunks, coverage
