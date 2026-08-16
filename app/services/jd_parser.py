"""Job description -> structured requirements.

The JD is the yardstick everything else is measured against, so the extraction
is deliberately opinionated about two things:

* **Every requirement gets a category** (`language`, `framework`, `tool`,
  `database`, `cloud`, `domain`, `practice`). The scoring engine routes
  categories to different weighted buckets — languages and databases count
  toward Technical Skills, frameworks and tools toward Tools/Frameworks — so an
  uncategorised requirement would land in the wrong bucket.
* **Every requirement gets an importance** (`required`, `preferred`,
  `nice_to_have`), which becomes its weight. A "nice to have" Kubernetes
  mention should not sink a candidate the way a hard requirement does.

JD parses contain no personal data, so unlike resumes they are safe to cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

VALID_CATEGORIES = {"language", "framework", "tool", "database", "cloud", "domain", "practice"}
VALID_IMPORTANCE = {"required", "preferred", "nice_to_have"}
EDUCATION_LEVELS = ["none", "school", "diploma", "bachelors", "masters", "phd"]


class JDError(Exception):
    pass


@dataclass
class JobRequirements:
    role_title: str | None = None
    seniority: str | None = None
    skills: list[dict] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    domain_knowledge: list[str] = field(default_factory=list)
    engineering_practices: list[str] = field(default_factory=list)
    min_years_experience: float | None = None
    experience_domains: list[str] = field(default_factory=list)
    education_min_level: str | None = None
    education_fields: list[str] = field(default_factory=list)

    def skills_in(self, categories: set[str]) -> list[dict]:
        return [skill for skill in self.skills if skill.get("category") in categories]

    def to_dict(self) -> dict:
        return {
            "role_title": self.role_title,
            "seniority": self.seniority,
            "skills": self.skills,
            "responsibilities": self.responsibilities,
            "domain_knowledge": self.domain_knowledge,
            "engineering_practices": self.engineering_practices,
            "min_years_experience": self.min_years_experience,
            "experience_domains": self.experience_domains,
            "education_min_level": self.education_min_level,
            "education_fields": self.education_fields,
        }


JD_SYSTEM_PROMPT = (
    "You extract structured requirements from a job description. Extract only what the "
    "text states — never invent requirements a hiring manager did not write.\n\n"
    "Respond ONLY with a JSON object with these keys:\n"
    '"role_title" (string|null), "seniority" (string|null, e.g. "intern","junior","mid","senior"),\n'
    '"skills": [{"name": str, "category": one of "language","framework","tool","database",'
    '"cloud","domain","practice", "importance": one of "required","preferred","nice_to_have", '
    '"reason": short quote or paraphrase of where this comes from in the JD}],\n'
    '"responsibilities": [str], "domain_knowledge": [str], "engineering_practices": [str] '
    "(testing, code review, CI/CD, documentation and similar),\n"
    '"min_years_experience": number|null — only if the JD states it,\n'
    '"experience_domains": [str] — the kinds of work the experience should be in,\n'
    '"education_min_level": one of "none","school","diploma","bachelors","masters","phd"|null,\n'
    '"education_fields": [str].\n\n'
    "Split compound requirements: 'experience with React and Vue' is two skills. "
    "Mark something as \"required\" only when the JD frames it as a must; language like "
    "'bonus', 'plus', 'nice to have' maps to nice_to_have."
)


def fingerprint(job_description: str) -> str:
    """Stable cache key / DB reference for a JD without storing the JD itself."""
    return hashlib.sha256(job_description.strip().encode("utf-8")).hexdigest()


def _normalise_skill(raw: dict) -> dict | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    category = str(raw.get("category") or "").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "tool"  # safest default: counts toward the lighter bucket

    importance = str(raw.get("importance") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if importance not in VALID_IMPORTANCE:
        importance = "required"

    return {
        "name": name,
        "category": category,
        "importance": importance,
        "reason": str(raw.get("reason") or "").strip() or None,
    }


def _coerce(data: dict) -> JobRequirements:
    def as_list(value) -> list:
        if isinstance(value, list):
            return value
        return [] if value in (None, "", {}) else [value]

    skills: list[dict] = []
    seen: set[str] = set()
    for raw in as_list(data.get("skills")):
        if not isinstance(raw, dict):
            continue
        skill = _normalise_skill(raw)
        if skill and skill["name"].lower() not in seen:
            seen.add(skill["name"].lower())
            skills.append(skill)

    years = data.get("min_years_experience")
    if years is not None:
        try:
            years = float(years)
        except (TypeError, ValueError):
            years = None

    level = str(data.get("education_min_level") or "").strip().lower() or None
    if level not in EDUCATION_LEVELS:
        level = None

    return JobRequirements(
        role_title=(data.get("role_title") or None),
        seniority=(data.get("seniority") or None),
        skills=skills,
        responsibilities=[str(item) for item in as_list(data.get("responsibilities")) if item],
        domain_knowledge=[str(item) for item in as_list(data.get("domain_knowledge")) if item],
        engineering_practices=[str(item) for item in as_list(data.get("engineering_practices")) if item],
        min_years_experience=years,
        experience_domains=[str(item) for item in as_list(data.get("experience_domains")) if item],
        education_min_level=level,
        education_fields=[str(item) for item in as_list(data.get("education_fields")) if item],
    )


async def parse_job_description(job_description: str, use_cache: bool = True) -> JobRequirements:
    text = (job_description or "").strip()
    if len(text) < 40:
        raise JDError("That job description is too short to analyse. Paste the full posting.")

    cache_key = f"jd:{fingerprint(text)}"
    if use_cache:
        try:
            from app.services.cache import cache_get

            cached = await cache_get(cache_key)
            if cached:
                return _coerce(cached)
        except Exception:  # noqa: BLE001 - a cache miss must never break the request
            logger.debug("JD cache unavailable", exc_info=True)

    from app.services.ai_engine import get_client

    client = get_client()
    response = await client.chat.completions.create(
        model=settings.match_model,
        messages=[
            {"role": "system", "content": JD_SYSTEM_PROMPT},
            {"role": "user", "content": f"JOB DESCRIPTION\n{text[:20000]}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    try:
        data = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise JDError("The job description could not be parsed into requirements.") from exc

    requirements = _coerce(data)
    if not requirements.skills:
        raise JDError("No concrete skills or requirements were found in that job description.")

    if use_cache:
        try:
            from app.services.cache import cache_set

            await cache_set(cache_key, requirements.to_dict(), ttl=settings.jd_cache_ttl_seconds)
        except Exception:  # noqa: BLE001
            logger.debug("JD cache write failed", exc_info=True)

    logger.info("JD parsed: %d requirements for '%s'", len(requirements.skills), requirements.role_title)
    return requirements
