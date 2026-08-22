"""Resume ingestion: PDF -> validated text -> structured, job-relevant JSON.

Three rules shape this module.

**Never invent.** The extraction prompt is explicitly told to return null rather
than guess, and every field on `ResumeProfile` is optional. A resume that omits
graduation dates produces nulls, not plausible-looking dates.

**Never score on protected characteristics.** Before any text reaches the LLM,
`scrub_protected_content` strips lines carrying gender, age, date of birth,
marital status, nationality, religion, caste, photo references and personal
contact details. The prompt repeats the prohibition, and `ResumeProfile` has
nowhere to put such a field even if a model tried to return one.

**Never retain the document.** Callers hand this module bytes; nothing is
written to disk here, and `extract_text` holds the document open only for as
long as it takes to read the pages. Raw resume text is never logged.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PDF_MAGIC = b"%PDF-"


class ResumeError(Exception):
    """Base for every user-correctable problem with an uploaded resume."""


class InvalidPDFError(ResumeError):
    pass


class ResumeTooLargeError(ResumeError):
    pass


class EmptyResumeError(ResumeError):
    """Parsed fine but contained no extractable text — usually a scanned image."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate_upload(data: bytes, content_type: str | None = None, filename: str | None = None) -> None:
    """Cheap checks before any parsing work. Magic bytes are checked as well as
    the declared content type, because the client-supplied type is trivially
    spoofed."""
    if not data:
        raise InvalidPDFError("The uploaded file is empty.")

    if len(data) > settings.resume_max_bytes:
        limit_mb = settings.resume_max_bytes / 1_000_000
        raise ResumeTooLargeError(f"Resume exceeds the {limit_mb:.0f} MB limit.")

    if not data.startswith(PDF_MAGIC):
        raise InvalidPDFError("That file is not a PDF (missing the PDF header).")

    if content_type and "pdf" not in content_type.lower():
        raise InvalidPDFError(f"Expected a PDF upload, got content type '{content_type}'.")

    if filename and not filename.lower().endswith(".pdf"):
        raise InvalidPDFError("Expected a file with a .pdf extension.")


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #


def extract_text(data: bytes) -> str:
    """PDF bytes -> plain text, via PyMuPDF. Never touches the filesystem."""
    # PyMuPDF is importable as `pymupdf` since 1.24; `fitz` is the legacy name
    # and now emits a deprecation warning. Try the modern one first.
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz  # noqa: F401 - legacy PyMuPDF entry point
        except ImportError as exc:  # pragma: no cover - dependency is in requirements
            raise ResumeError(
                "PyMuPDF is not installed; run pip install -r requirements.txt"
            ) from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several types
        raise InvalidPDFError("That PDF could not be opened; it may be corrupt or password-protected.") from exc

    try:
        if document.needs_pass:
            raise InvalidPDFError("That PDF is password-protected. Please upload an unlocked copy.")

        pages = min(document.page_count, settings.resume_max_pages)
        chunks = [document.load_page(index).get_text("text") for index in range(pages)]
    finally:
        document.close()

    text = "\n".join(chunks).strip()
    if not text:
        raise EmptyResumeError(
            "No text could be extracted. If this is a scanned resume, upload a text-based PDF instead."
        )

    # Log shape only — never content.
    logger.info("Resume parsed: %d pages, %d characters", pages, len(text))
    return text[: settings.resume_max_chars]


# --------------------------------------------------------------------------- #
# Fairness: strip protected and personal data before it reaches the model
# --------------------------------------------------------------------------- #

_PROTECTED_LINE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(gender|sex)\s*[:\-]",
        r"\b(date\s+of\s+birth|d\.?o\.?b\.?|birth\s*date)\b",
        r"\bage\s*[:\-]\s*\d{1,2}\b",
        r"\b(marital\s+status|spouse|father'?s\s+name|mother'?s\s+name)\b",
        r"\b(nationality|citizenship|religion|caste|ethnicity|race)\s*[:\-]",
        r"\b(passport|aadhaar|aadhar|ssn|social\s+security)\b",
        r"\b(photo|photograph|headshot)\s*[:\-]",
        r"\b(political|party\s+affiliation)\b",
    )
]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# Phone numbers vary far too much by country for a single rigid pattern
# (+91 98765 43210, (555) 123-4567, +44 20 7946 0958). Instead: find runs of
# digits and separators, then keep only those with a phone-like digit count.
# The digit-count floor is what stops date ranges like "Jan 2023 - Jan 2025"
# from being redacted as phone numbers.
_PHONE_CANDIDATE = re.compile(r"(?<![\w])\(?\+?[\d][\d\s().\-]{6,20}\d")
_PHONE_MIN_DIGITS = 9
_PHONE_MAX_DIGITS = 15


def _redact_phones(line: str) -> tuple[str, bool]:
    found = False

    def replace(match: re.Match) -> str:
        nonlocal found
        digits = sum(character.isdigit() for character in match.group(0))
        if _PHONE_MIN_DIGITS <= digits <= _PHONE_MAX_DIGITS:
            found = True
            return "[phone redacted]"
        return match.group(0)

    return _PHONE_CANDIDATE.sub(replace, line), found


def scrub_protected_content(text: str) -> tuple[str, list[str]]:
    """Removes protected-characteristic lines and personal contact details.

    Returns the cleaned text plus the categories removed, so the API can be
    transparent about it without ever echoing the content itself.
    """
    removed: set[str] = set()
    kept_lines: list[str] = []

    for line in text.split("\n"):
        if any(pattern.search(line) for pattern in _PROTECTED_LINE_PATTERNS):
            removed.add("protected characteristics")
            continue
        if _EMAIL.search(line):
            line = _EMAIL.sub("[email redacted]", line)
            removed.add("contact details")
        line, had_phone = _redact_phones(line)
        if had_phone:
            removed.add("contact details")
        kept_lines.append(line)

    return "\n".join(kept_lines), sorted(removed)


# --------------------------------------------------------------------------- #
# Structured output
# --------------------------------------------------------------------------- #


@dataclass
class ResumeProfile:
    """Structured resume. Every field is optional — absence is represented as
    None or an empty list, never as an invented value."""

    name: str | None = None
    summary: str | None = None
    education: list[dict] = field(default_factory=list)
    experience: list[dict] = field(default_factory=list)
    skills: dict[str, list[str]] = field(default_factory=dict)
    skill_mentions: list[dict] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    total_experience_months: int | None = None
    redacted_categories: list[str] = field(default_factory=list)
    unverified_skills: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    def all_skills(self) -> list[str]:
        names = {name for group in self.skills.values() for name in group}
        names.update(mention.get("skill", "") for mention in self.skill_mentions)
        for project in self.projects:
            names.update(project.get("technologies") or [])
        for role in self.experience:
            names.update(role.get("technologies") or [])
        return sorted(name for name in names if name)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "education": self.education,
            "experience": self.experience,
            "skills": self.skills,
            "skill_mentions": self.skill_mentions,
            "certifications": self.certifications,
            "projects": self.projects,
            "achievements": self.achievements,
            "total_experience_months": self.total_experience_months,
            "redacted_categories": self.redacted_categories,
            "unverified_skills": self.unverified_skills,
            "parse_warnings": self.parse_warnings,
        }


EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured data from a resume. You are a parser, not an evaluator.\n\n"
    "ABSOLUTE RULES:\n"
    "1. Extract ONLY what the text states. Never infer, complete, or embellish. If a "
    "field is not present, use null (or an empty array). A missing graduation year is "
    "null — never a guess.\n"
    "2. Never extract or infer gender, age, date of birth, marital status, nationality, "
    "citizenship, religion, caste, ethnicity, race, political affiliation, photographs, "
    "or personal contact details. Omit them entirely even if present in the text.\n"
    "3. Copy skill names as written (e.g. 'PyTorch', not 'pytorch').\n\n"
    "Respond ONLY with a JSON object with these keys:\n"
    '"name" (string|null), "summary" (string|null),\n'
    '"education": [{"degree","field","institution","start","end","level"}] where level is '
    'one of "phd","masters","bachelors","diploma","school", and unstated dates are null,\n'
    '"experience": [{"role","company","type","start","end","duration_months","description",'
    '"technologies":[...]}] where type is "job"|"internship"|"freelance"|"research" and '
    "duration_months is null unless the dates state it,\n"
    '"skills": {"languages":[],"frameworks":[],"databases":[],"cloud":[],"tools":[],"other":[]},\n'
    '"skill_mentions": [{"skill": str, "contexts": [str]}] — for each skill, where it appears: '
    '"skills_section", "experience:<company>", "project:<name>", "certification", or "summary". '
    "This is important: a skill only listed in a skills section has weaker evidence than one "
    "used in a described role.\n"
    '"certifications": [str], "projects": [{"name","description","technologies":[...],'
    '"achievements":[str]}], "achievements": [str],\n'
    '"total_experience_months": integer|null — only if the resume states total experience or '
    "the dates make it unambiguous.\n"
)


def _coerce_profile(data: dict[str, Any]) -> ResumeProfile:
    """Defensive coercion — a model can return a string where a list belongs."""

    def as_list(value) -> list:
        if isinstance(value, list):
            return value
        if value in (None, "", {}):
            return []
        return [value]

    def as_str(value) -> str | None:
        if value is None or isinstance(value, str):
            return value or None
        return str(value)

    skills_raw = data.get("skills") or {}
    skills = {
        key: [str(item) for item in as_list(skills_raw.get(key)) if item]
        for key in ("languages", "frameworks", "databases", "cloud", "tools", "other")
    }

    months = data.get("total_experience_months")
    if not isinstance(months, int):
        try:
            months = int(months)
        except (TypeError, ValueError):
            months = None

    return ResumeProfile(
        name=as_str(data.get("name")),
        summary=as_str(data.get("summary")),
        education=[item for item in as_list(data.get("education")) if isinstance(item, dict)],
        experience=[item for item in as_list(data.get("experience")) if isinstance(item, dict)],
        skills=skills,
        skill_mentions=[item for item in as_list(data.get("skill_mentions")) if isinstance(item, dict)],
        certifications=[str(item) for item in as_list(data.get("certifications")) if item],
        projects=[item for item in as_list(data.get("projects")) if isinstance(item, dict)],
        achievements=[str(item) for item in as_list(data.get("achievements")) if item],
        total_experience_months=months,
    )


def verify_against_source(profile: "ResumeProfile", source_text: str) -> "ResumeProfile":
    """Drop any extracted skill that does not actually appear in the resume.

    The extraction prompt forbids inventing, but a prompt is a request, not a
    guarantee. This is the enforcement: every skill name is matched back against
    the source text (alias-aware, so a resume saying "Postgres" still validates
    an extracted "PostgreSQL"). Anything that cannot be found is moved out of
    `skills` into `unverified_skills` and surfaced as a warning.

    Unverified skills are excluded from evidence lookup rather than deleted
    outright, so nothing disappears silently — but they also cannot earn a
    candidate credit they have no textual basis for. This matters more than it
    looks: an invented skill would otherwise flow straight into the
    deterministic score as genuine resume evidence.
    """
    from app.services.evidence import _mentions, variants

    unverified: list[str] = []

    for group, names in list(profile.skills.items()):
        kept = []
        for name in names:
            if _mentions(source_text, variants(name)):
                kept.append(name)
            else:
                unverified.append(name)
        profile.skills[group] = kept

    verified_mentions = []
    for mention in profile.skill_mentions:
        name = str(mention.get("skill", ""))
        if _mentions(source_text, variants(name)):
            verified_mentions.append(mention)
        elif name and name not in unverified:
            unverified.append(name)
    profile.skill_mentions = verified_mentions

    if unverified:
        profile.unverified_skills = sorted(set(unverified))
        profile.parse_warnings.append(
            f"{len(profile.unverified_skills)} extracted skill(s) could not be found in the "
            "resume text and were excluded from scoring: " + ", ".join(profile.unverified_skills[:8])
        )
        logger.info("Extraction verification dropped %d unfounded skill(s)", len(profile.unverified_skills))

    return profile


async def structure_resume(text: str) -> ResumeProfile:
    """Scrubbed resume text -> ResumeProfile, via the shared LLM adapter."""
    from app.services.ai_engine import get_client

    cleaned, redacted = scrub_protected_content(text)

    client = get_client()
    response = await client.chat.completions.create(
        model=settings.extraction_model or settings.match_model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"RESUME TEXT\n{cleaned}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    try:
        data = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ResumeError("The resume could not be structured; the extraction returned invalid JSON.") from exc

    profile = _coerce_profile(data)
    profile.redacted_categories = redacted

    # Enforce the "never invent" rule rather than merely asking for it.
    if settings.verify_extraction:
        profile = verify_against_source(profile, cleaned)

    if not profile.all_skills():
        profile.parse_warnings.append("No skills were found in this resume.")
    if not profile.experience:
        profile.parse_warnings.append("No work experience or internships were found.")

    logger.info(
        "Resume structured: %d roles, %d projects, %d skills",
        len(profile.experience), len(profile.projects), len(profile.all_skills()),
    )
    return profile


async def parse_resume_pdf(data: bytes, content_type: str | None = None, filename: str | None = None) -> ResumeProfile:
    """Full path: validate -> extract -> scrub -> structure."""
    validate_upload(data, content_type, filename)
    text = extract_text(data)
    return await structure_resume(text)
