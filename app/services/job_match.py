"""Orchestration for JD + resume + GitHub matching.

Order of operations, and who decides what:

    JD text ──► jd_parser (LLM)  ─┐
    resume PDF ─► resume_parser (LLM, structuring only)
    username ──► pipeline.collect_and_analyze (deterministic, cached)
                                   │
                                   ▼
                   project relevance (embeddings, reused from repo chat)
                                   │
                                   ▼
                   match_engine.compute_match  ← the numbers come from here
                                   │
                                   ▼
                   LLM narration: explanation, interview questions, roadmap
                                   (given the computed scores; cannot change them)

The model never sees a scoring weight and never returns a percentage that ends
up in the report. It reads and it explains; arithmetic stays in Python.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import JobMatchReport
from app.services import evidence as ev
from app.services import jd_parser, match_engine, pipeline
from app.services.embeddings import get_embedder, tokenize
from app.services.jd_parser import JobRequirements
from app.services.vector_store import cosine_similarity

logger = logging.getLogger(__name__)
settings = get_settings()

DISCLAIMER = (
    "AI-assisted candidate–role analysis. This report is decision support, not a decision: "
    "it reflects only publicly available GitHub activity and the supplied resume, both of "
    "which are partial views of a candidate's work. It must not be the sole basis for any "
    "employment decision. Scores are computed from job-relevant professional evidence only — "
    "no demographic or personal characteristics are used at any point."
)


# --------------------------------------------------------------------------- #
# Project relevance
# --------------------------------------------------------------------------- #


def _project_text(project: dict) -> str:
    parts = [
        project.get("name") or "",
        project.get("description") or "",
        " ".join(project.get("technologies") or []),
        " ".join(project.get("topics") or []),
        project.get("primary_language") or "",
        " ".join((project.get("languages") or {}).keys()),
    ]
    return " ".join(part for part in parts if part).strip()


def _jd_text(requirements: JobRequirements) -> str:
    return " ".join(
        [requirements.role_title or ""]
        + [skill["name"] for skill in requirements.skills]
        + requirements.responsibilities
        + requirements.domain_knowledge
    ).strip()


def _skill_overlap(project_text: str, requirements: JobRequirements) -> tuple[float, list[str]]:
    """Fraction of JD skills the project actually names — the lexical half of
    relevance, and the part that produces the citable 'why'."""
    if not requirements.skills:
        return 0.0, []
    matched = [
        skill["name"] for skill in requirements.skills
        if ev._mentions(project_text, ev.variants(skill["name"]))
    ]
    return len(matched) / len(requirements.skills), matched


async def score_project_relevance(requirements: JobRequirements, resume: dict, analysis: dict) -> list[dict]:
    """Semantic + lexical relevance for every GitHub repo and resume project.

    Embeddings alone rate a 'Calculator' repo surprisingly high against any
    software JD, because everything is software. Requiring the project to name
    actual JD skills is what separates 'Face Recognition' from 'Calculator' for
    a computer vision role.
    """
    candidates: list[dict] = []

    for repo in analysis.get("repositories") or []:
        if repo.get("is_archived"):
            continue
        candidates.append({
            "name": repo.get("name", ""),
            "source": "github",
            "text": _project_text(repo),
            "stars": repo.get("stars", 0),
        })

    for project in resume.get("projects") or []:
        candidates.append({
            "name": project.get("name") or "Untitled project",
            "source": "resume",
            "text": _project_text(project),
            "stars": None,
        })

    if not candidates:
        return []

    jd_text = _jd_text(requirements)
    embedder = get_embedder()
    try:
        vectors = await embedder.embed_documents([item["text"] for item in candidates])
        jd_vector = await embedder.embed_query(jd_text)
    except Exception:  # noqa: BLE001 - fall back to lexical-only rather than fail
        logger.warning("Embedding failed; project relevance falls back to lexical overlap", exc_info=True)
        vectors = [[] for _ in candidates]
        jd_vector = []

    results: list[dict] = []
    for item, vector in zip(candidates, vectors):
        overlap, matched = _skill_overlap(item["text"], requirements)
        similarity = max(0.0, cosine_similarity(jd_vector, vector)) if vector and jd_vector else 0.0

        # Overlap is weighted higher: naming the actual required technologies is
        # stronger evidence than sitting near the JD in embedding space.
        relevance = 100.0 * (0.4 * min(1.0, similarity) + 0.6 * min(1.0, overlap * 2.5))

        results.append({
            "project": item["name"],
            "source": item["source"],
            "relevance": round(match_engine.clamp(relevance), 1),
            "matched_requirements": matched,
            "semantic_similarity": round(similarity, 3),
            "stars": item["stars"],
        })

    return sorted(results, key=lambda item: item["relevance"], reverse=True)


# --------------------------------------------------------------------------- #
# Narration (explanations, questions, roadmap)
# --------------------------------------------------------------------------- #

NARRATION_SYSTEM_PROMPT = (
    "You are a senior engineering hiring partner writing up a candidate–role analysis. "
    "The scores have ALREADY been computed by a deterministic engine and are given to you. "
    "Your job is to explain and to ask good questions — never to recompute, dispute, or "
    "restate a different percentage.\n\n"
    "RULES:\n"
    "1. Never claim a candidate lacks a skill marked UNKNOWN. Say there is no public "
    "evidence either way, and treat it as something to verify.\n"
    "2. Never reference or infer age, gender, nationality, race, religion or any personal "
    "characteristic. Evaluate professional evidence only.\n"
    "3. Ground statements in the evidence given.\n\n"
    "Respond ONLY with a JSON object with these keys:\n"
    '"explanation": 3-5 sentences on why the fit lands where it does, naming the strongest '
    "evidence and the biggest gap;\n"
    '"strengths": [str] — up to 5, each tied to concrete evidence;\n'
    '"concerns": [str] — up to 5, phrased as verification needs rather than accusations;\n'
    '"interview_questions": [{"category": one of "technical","resume","project","skill_gap",'
    '"behavioral", "question": str, "why": str}] — {question_count} questions, specific to THIS '
    "candidate and THIS role. Reference their actual projects, roles and gaps by name. "
    "Cover all five categories.\n"
    '"learning_recommendations": [{"skill": str, "why": str, "steps": [str]}] — for the '
    "weakest and least-evidenced required skills, 3-5 concrete progressive steps each, "
    "ending in something the candidate could build."
)


def _narration_context(requirements: JobRequirements, resume: dict, analysis: dict, computed: dict) -> str:
    """Compact, job-relevant context. Note what is *not* here: no resume name,
    no contact details, no demographic fields."""
    return json.dumps(
        {
            "role": requirements.role_title,
            "seniority": requirements.seniority,
            "responsibilities": requirements.responsibilities[:8],
            "computed_scores": {
                "overall_match": computed["overall_match"],
                "confidence": computed["confidence"],
                "recommendation": computed["recommendation"],
                "by_category": {
                    name: block["score"] for name, block in computed["score_breakdown"].items()
                },
            },
            "skills": [
                {
                    "skill": item["skill"],
                    "status": item["status"],
                    "importance": item["importance"],
                    "resume_evidence": item["evidence"]["resume"][:3],
                    "github_evidence": item["evidence"]["github"][:3],
                }
                for item in computed["skill_analysis"]
            ],
            "top_projects": computed["project_analysis"][:6],
            "experience": [
                {
                    "role": role.get("role"),
                    "company": role.get("company"),
                    "type": role.get("type"),
                    "duration_months": role.get("duration_months"),
                    "technologies": role.get("technologies"),
                }
                for role in (resume.get("experience") or [])[:6]
            ],
            "education": resume.get("education") or [],
            "github_summary": {
                "public_repos": (analysis.get("profile") or {}).get("public_repos"),
                "top_languages": list(
                    ((analysis.get("languages") or {}).get("distribution_percent") or {})
                )[:6],
                "developer_score": (analysis.get("developer_score") or {}).get("overall_score"),
            },
            "discrepancies": computed.get("evidence_discrepancies", [])[:6],
        },
        default=str,
    )


async def generate_narration(requirements: JobRequirements, resume: dict, analysis: dict, computed: dict) -> dict:
    from app.services.ai_engine import get_client

    client = get_client()
    response = await client.chat.completions.create(
        model=settings.narration_model or settings.match_model,
        messages=[
            {"role": "system", "content": NARRATION_SYSTEM_PROMPT.replace(
                "{question_count}", str(settings.interview_question_count))},
            {"role": "user", "content": _narration_context(requirements, resume, analysis, computed)},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    try:
        data = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Narration returned invalid JSON; continuing with scores only")
        return {"explanation": None, "strengths": [], "concerns": [],
                "interview_questions": [], "learning_recommendations": []}

    return {
        "explanation": data.get("explanation"),
        "strengths": data.get("strengths") or [],
        "concerns": data.get("concerns") or [],
        "interview_questions": data.get("interview_questions") or [],
        "learning_recommendations": data.get("learning_recommendations") or [],
    }


# --------------------------------------------------------------------------- #
# Top level
# --------------------------------------------------------------------------- #


def _redact_resume_for_storage(resume: dict) -> dict:
    """What we keep: the job-relevant structure. What we drop: the candidate's
    name and free-text summary, so a stored report is not a stored resume."""
    keep = dict(resume)
    keep.pop("name", None)
    keep.pop("summary", None)
    return keep


async def run_job_match(
    username: str,
    company: str,
    job_description: str,
    resume: dict,
    db: AsyncSession | None = None,
    user_id: int | None = None,
) -> dict:
    """Full analysis. `resume` is already-structured data — this function never
    sees the PDF, which is the point: the file is gone by the time we get here."""
    requirements = await jd_parser.parse_job_description(job_description)
    analysis = await pipeline.collect_and_analyze(username)

    project_relevance = await score_project_relevance(requirements, resume, analysis)
    computed = match_engine.compute_match(requirements, resume, analysis, project_relevance)

    assessments = match_engine.assess_skills(requirements, resume, analysis)
    computed["evidence_discrepancies"] = match_engine.detect_discrepancies(assessments, analysis)

    try:
        narration = await generate_narration(requirements, resume, analysis, computed)
    except Exception:  # noqa: BLE001 - the deterministic report still stands alone
        logger.exception("Narration failed; returning scores without commentary")
        narration = {"explanation": None, "strengths": [], "concerns": [],
                     "interview_questions": [], "learning_recommendations": []}

    report = {
        "github_username": username,
        "company": company,
        "role_title": requirements.role_title,
        "generated_at": datetime.utcnow().isoformat(),
        **computed,
        **narration,
        "jd_requirements": requirements.to_dict(),
        "resume_signals": {
            "roles": len(resume.get("experience") or []),
            "projects": len(resume.get("projects") or []),
            "skills_found": len(resume.get("skills", {}).get("languages", []) or []) or None,
            "redacted_categories": resume.get("redacted_categories") or [],
            "parse_warnings": resume.get("parse_warnings") or [],
        },
        "methodology": {
            "weights_percent": {name: round(weight * 100, 1) for name, weight in match_engine.WEIGHTS.items()},
            "unknown_handling": (
                "Skills with no public evidence either way are marked UNKNOWN, contribute nothing "
                "to the score, count at half weight in the denominator, and reduce confidence. "
                "They are never reported as skills the candidate lacks."
            ),
            "scoring": "All percentages are computed deterministically in Python; the language model "
                       "extracts and explains but does not score.",
        },
        "disclaimer": DISCLAIMER,
    }

    if db is not None:
        try:
            db.add(JobMatchReport(
                user_id=user_id,
                github_username=username,
                company=company,
                role_title=requirements.role_title,
                jd_fingerprint=jd_parser.fingerprint(job_description),
                overall_match=report["overall_match"],
                confidence=report["confidence"],
                recommendation=report["recommendation"],
                report={**report, "stored_resume_signals": _redact_resume_for_storage(resume).get("skills", {})},
            ))
            await db.commit()
        except Exception:  # noqa: BLE001 - never lose a computed report to a DB hiccup
            logger.exception("Failed to persist job match report")
            await db.rollback()

    logger.info(
        "Job match complete: %s vs %s — %.1f%% (%s), confidence %.1f%%",
        username, company, report["overall_match"], report["recommendation"], report["confidence"],
    )
    return report
