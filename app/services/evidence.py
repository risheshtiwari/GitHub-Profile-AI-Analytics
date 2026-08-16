"""Evidence lookup — where a skill is actually demonstrated.

Everything downstream depends on this being honest. A skill is not "found"
because a model felt it was; it is found because a specific, quotable artefact
mentions it: a language in the GitHub language distribution, a repository topic,
a listed skill in the resume, a technology attached to a described role.

Each hit is returned as a human-readable string that ends up verbatim in the
report, so a reviewer can check every claim against the source.

Pure functions — no LLM, no network, no DB. Fully unit tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Aliases matter more than they look: a JD asking for "Postgres" must match a
# resume saying "PostgreSQL" and a repo tagged "postgresql".
ALIASES: dict[str, set[str]] = {
    "javascript": {"js", "node", "nodejs", "node.js", "ecmascript"},
    "typescript": {"ts"},
    "python": {"py", "python3"},
    "postgresql": {"postgres", "psql", "postgre"},
    "mysql": {"mariadb"},
    "mongodb": {"mongo"},
    "kubernetes": {"k8s"},
    "docker": {"containers", "containerisation", "containerization"},
    "amazon web services": {"aws", "ec2", "s3", "lambda"},
    "google cloud platform": {"gcp", "google cloud"},
    "microsoft azure": {"azure"},
    "pytorch": {"torch"},
    "tensorflow": {"tf", "keras"},
    "scikit-learn": {"sklearn", "scikit learn"},
    "c++": {"cpp", "cplusplus"},
    "c#": {"csharp", "c sharp", "dotnet", ".net"},
    "react": {"reactjs", "react.js"},
    "vue": {"vuejs", "vue.js"},
    "angular": {"angularjs"},
    "fastapi": {"fast api"},
    "postgres sql": {"postgresql"},
    "natural language processing": {"nlp"},
    "computer vision": {"cv", "opencv", "image processing"},
    "machine learning": {"ml"},
    "deep learning": {"dl", "neural networks"},
    "continuous integration": {"ci", "ci/cd", "github actions", "jenkins", "gitlab ci"},
    "unit testing": {"pytest", "unittest", "jest", "testing", "tests"},
    "rest api": {"rest", "restful", "api development"},
    "sql": {"queries", "rdbms"},
}

# Skills whose presence is inherently hard to evidence publicly — used to keep
# the "missing vs unknown" call conservative.
PRACTICE_CATEGORY = "practice"


def normalise(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def variants(name: str) -> set[str]:
    """All spellings of a skill worth matching against."""
    base = normalise(name)
    forms = {base}
    forms.update(ALIASES.get(base, set()))
    for canonical, aliases in ALIASES.items():
        if base in aliases:
            forms.add(canonical)
            forms.update(aliases)
    forms.discard("")
    return forms


def _mentions(haystack: str, forms: set[str]) -> bool:
    """Word-boundary match, so 'r' doesn't match 'react' and 'go' doesn't match
    'google'. Skills containing regex metacharacters (C++, C#) are escaped."""
    text = normalise(haystack)
    if not text:
        return False
    for form in forms:
        if not form:
            continue
        pattern = rf"(?<![\w+#]){re.escape(form)}(?![\w+#])"
        if re.search(pattern, text):
            return True
    return False


@dataclass
class Evidence:
    """Where a skill was found, and how strongly."""

    resume: list[str] = field(default_factory=list)
    github: list[str] = field(default_factory=list)
    resume_is_usage: bool = False   # used in a role/project, not just listed
    github_repo_count: int = 0
    github_code_share: float = 0.0  # % of public code in this language

    @property
    def in_resume(self) -> bool:
        return bool(self.resume)

    @property
    def in_github(self) -> bool:
        return bool(self.github)

    def to_dict(self) -> dict:
        return {
            "resume": self.resume,
            "github": self.github,
            "resume_is_usage": self.resume_is_usage,
            "github_repo_count": self.github_repo_count,
            "github_code_share": round(self.github_code_share, 2),
        }


# --------------------------------------------------------------------------- #
# Resume side
# --------------------------------------------------------------------------- #


def resume_evidence(skill: str, resume: dict) -> Evidence:
    """Finds a skill in structured resume data, distinguishing a bare listing
    from demonstrated usage — that distinction drives partial vs weak."""
    forms = variants(skill)
    evidence = Evidence()

    for group, names in (resume.get("skills") or {}).items():
        for name in names or []:
            if _mentions(name, forms):
                evidence.resume.append(f"Listed under {group} in the skills section")
                break

    for mention in resume.get("skill_mentions") or []:
        if not _mentions(str(mention.get("skill", "")), forms):
            continue
        for context in mention.get("contexts") or []:
            context = str(context)
            if context.startswith("experience:"):
                evidence.resume.append(f"Used in a role at {context.split(':', 1)[1].strip()}")
                evidence.resume_is_usage = True
            elif context.startswith("project:"):
                evidence.resume.append(f"Used in project '{context.split(':', 1)[1].strip()}'")
                evidence.resume_is_usage = True
            elif context == "certification":
                evidence.resume.append("Named in a certification")
                evidence.resume_is_usage = True

    for role in resume.get("experience") or []:
        technologies = role.get("technologies") or []
        where = role.get("company") or role.get("role") or "a listed role"
        if any(_mentions(str(item), forms) for item in technologies):
            evidence.resume.append(f"Technology of record at {where}")
            evidence.resume_is_usage = True
        elif _mentions(str(role.get("description") or ""), forms):
            evidence.resume.append(f"Described in the {where} role")
            evidence.resume_is_usage = True

    for project in resume.get("projects") or []:
        technologies = project.get("technologies") or []
        name = project.get("name") or "a listed project"
        if any(_mentions(str(item), forms) for item in technologies) or _mentions(
            str(project.get("description") or ""), forms
        ):
            evidence.resume.append(f"Used in resume project '{name}'")
            evidence.resume_is_usage = True

    for certification in resume.get("certifications") or []:
        if _mentions(str(certification), forms):
            evidence.resume.append(f"Certification: {certification}")
            evidence.resume_is_usage = True

    # De-duplicate while preserving order.
    evidence.resume = list(dict.fromkeys(evidence.resume))
    return evidence


# --------------------------------------------------------------------------- #
# GitHub side
# --------------------------------------------------------------------------- #


def github_evidence(skill: str, analysis: dict) -> Evidence:
    """Finds a skill in the existing GitHub analysis output (the dict returned
    by pipeline.collect_and_analyze)."""
    forms = variants(skill)
    evidence = Evidence()

    distribution = (analysis.get("languages") or {}).get("distribution_percent") or {}
    for language, share in distribution.items():
        if _mentions(language, forms):
            evidence.github.append(f"{language} is {share:.1f}% of public code")
            evidence.github_code_share = max(evidence.github_code_share, float(share))

    repos = analysis.get("repositories") or []
    matched_repos: list[str] = []
    for repo in repos:
        name = repo.get("name", "")
        hit_reason = None

        if any(_mentions(str(topic), forms) for topic in repo.get("topics") or []):
            hit_reason = "topic"
        elif _mentions(str(repo.get("primary_language") or ""), forms):
            hit_reason = "primary language"
        elif any(_mentions(str(language), forms) for language in (repo.get("languages") or {})):
            hit_reason = "language"
        elif _mentions(name, forms):
            hit_reason = "repository name"

        if hit_reason:
            stars = repo.get("stars", 0)
            matched_repos.append(f"{name} ({hit_reason}, {stars}★)")

    if matched_repos:
        evidence.github_repo_count = len(matched_repos)
        evidence.github.extend(f"Repository {item}" for item in matched_repos[:5])
        if len(matched_repos) > 5:
            evidence.github.append(f"…and {len(matched_repos) - 5} more repositories")

    for item in (analysis.get("languages") or {}).get("ai_ml_ecosystem_detected") or []:
        if _mentions(str(item), forms):
            evidence.github.append(f"{item} detected in the AI/ML ecosystem scan")

    evidence.github = list(dict.fromkeys(evidence.github))
    return evidence


def combine(resume_side: Evidence, github_side: Evidence) -> Evidence:
    return Evidence(
        resume=resume_side.resume,
        github=github_side.github,
        resume_is_usage=resume_side.resume_is_usage,
        github_repo_count=github_side.github_repo_count,
        github_code_share=github_side.github_code_share,
    )


def gather(skill: str, resume: dict, analysis: dict) -> Evidence:
    return combine(resume_evidence(skill, resume), github_evidence(skill, analysis))


# --------------------------------------------------------------------------- #
# Practice evidence (engineering hygiene, from repository facts)
# --------------------------------------------------------------------------- #


def practice_evidence(analysis: dict) -> dict:
    """Deterministic engineering-practice signals straight from repo metadata."""
    repos = [repo for repo in analysis.get("repositories") or [] if not repo.get("is_archived")]
    total = len(repos) or 1

    with_readme = sum(1 for repo in repos if repo.get("has_readme"))
    with_license = sum(1 for repo in repos if repo.get("has_license"))
    with_tests = sum(
        1 for repo in repos
        if any(_mentions(str(topic), variants("unit testing")) for topic in repo.get("topics") or [])
    )
    with_ci = sum(
        1 for repo in repos
        if any(_mentions(str(topic), variants("continuous integration")) for topic in repo.get("topics") or [])
    )

    score_breakdown = analysis.get("developer_score") or {}

    return {
        "repos_considered": len(repos),
        "readme_ratio": with_readme / total,
        "license_ratio": with_license / total,
        "tests_ratio": with_tests / total,
        "ci_ratio": with_ci / total,
        "documentation_subscore": float(score_breakdown.get("documentation", 0.0)),
        "testing_subscore": float(score_breakdown.get("testing", 0.0)),
        "consistency_subscore": float(score_breakdown.get("consistency", 0.0)),
    }
