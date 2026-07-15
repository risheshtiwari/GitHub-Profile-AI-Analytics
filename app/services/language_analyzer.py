"""Phase 3 — Language Analytics."""

import math

BACKEND_LANGS = {
    "Python", "Java", "Go", "Rust", "C", "C++", "C#", "Ruby", "PHP", "Kotlin",
    "Scala", "Elixir", "Erlang", "Haskell",
}
FRONTEND_LANGS = {"JavaScript", "TypeScript", "HTML", "CSS", "Vue", "Svelte"}
AI_ML_KEYWORDS = {
    "Jupyter Notebook": "Jupyter", "Python": None,  # Python alone isn't proof of AI/ML use
}


def aggregate_languages(repo_languages: list[dict[str, int]]) -> dict[str, int]:
    """Sum byte counts for each language across all repos."""
    totals: dict[str, int] = {}
    for lang_map in repo_languages:
        for lang, byte_count in lang_map.items():
            totals[lang] = totals.get(lang, 0) + byte_count
    return totals


def language_distribution_percent(totals: dict[str, int]) -> dict[str, float]:
    total_bytes = sum(totals.values())
    if total_bytes == 0:
        return {}
    return {
        lang: round(100 * count / total_bytes, 1)
        for lang, count in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    }


def language_diversity_score(totals: dict[str, int]) -> float:
    """Shannon entropy normalized to 0-100. More languages, more evenly used => higher score."""
    total_bytes = sum(totals.values())
    if total_bytes == 0 or len(totals) <= 1:
        return 0.0
    entropy = 0.0
    for count in totals.values():
        p = count / total_bytes
        if p > 0:
            entropy -= p * math.log2(p)
    max_entropy = math.log2(len(totals))
    return round(100 * entropy / max_entropy, 1) if max_entropy > 0 else 0.0


def backend_frontend_ratio(totals: dict[str, int]) -> dict[str, float]:
    backend_bytes = sum(v for k, v in totals.items() if k in BACKEND_LANGS)
    frontend_bytes = sum(v for k, v in totals.items() if k in FRONTEND_LANGS)
    total = backend_bytes + frontend_bytes
    if total == 0:
        return {"backend_percent": 0.0, "frontend_percent": 0.0}
    return {
        "backend_percent": round(100 * backend_bytes / total, 1),
        "frontend_percent": round(100 * frontend_bytes / total, 1),
    }


def detect_ai_ml_ecosystem(repo_topics: list[list[str]], primary_languages: list[str]) -> list[str]:
    """Heuristic: flag AI/ML usage from repo topics (cheap, no extra API calls)."""
    ai_keywords = {
        "machine-learning", "deep-learning", "pytorch", "tensorflow", "scikit-learn",
        "nlp", "computer-vision", "llm", "ai", "neural-network", "keras", "transformers",
    }
    found = set()
    for topics in repo_topics:
        for t in topics or []:
            if t.lower() in ai_keywords:
                found.add(t.lower())
    if "Jupyter Notebook" in primary_languages:
        found.add("jupyter-notebook")
    return sorted(found)
