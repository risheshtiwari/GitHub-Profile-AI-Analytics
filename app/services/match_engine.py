"""The scoring engine — deterministic, auditable, no LLM anywhere in this file.

The model reads the JD, reads the resume, and says where skills appear. It does
**not** decide the number. Every percentage in the final report is computed here
from countable evidence, which is what makes the result reproducible: the same
inputs always yield the same score, and every score can be traced back to the
rule and the evidence that produced it.

Two design decisions carry most of the weight.

**Missing is not the same as unknown.** MISSING means the candidate demonstrably
does not show the skill — operationally, they show several peer skills in the
same category but not this one (four databases listed, not the one asked for).
UNKNOWN means there is simply no public evidence either way, which is the honest
verdict for most gaps: a resume is two pages and GitHub is only public work.
Unknowns therefore contribute nothing to the numerator but only half weight to
the denominator, and they push down *confidence* rather than masquerading as a
confirmed deficiency.

**Nothing protected feeds the score.** The inputs are skills, roles, projects,
education level and repository hygiene. There is no path from a demographic
attribute to any number here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services import evidence as ev
from app.services.jd_parser import EDUCATION_LEVELS, JobRequirements

settings = get_settings()

# Which JD categories feed which weighted bucket.
TECHNICAL_CATEGORIES = {"language", "database", "cloud", "domain"}
TOOLING_CATEGORIES = {"framework", "tool"}

STATUS_STRONG = "strong"
STATUS_PARTIAL = "partial"
STATUS_WEAK = "weak"
STATUS_MISSING = "missing"
STATUS_UNKNOWN = "unknown"

RECOMMENDATION_BANDS = [
    (90, "Excellent Fit"),
    (80, "Strong Fit"),
    (65, "Moderate Fit"),
    (50, "Weak Fit"),
    (0, "Poor Fit"),
]

WEIGHTS = {
    "technical_skills": settings.weight_technical_skills,
    "work_experience": settings.weight_work_experience,
    "project_relevance": settings.weight_project_relevance,
    "tools_frameworks": settings.weight_tools_frameworks,
    "education": settings.weight_education,
    "engineering_practices": settings.weight_engineering_practices,
}

_total_weight = round(sum(WEIGHTS.values()), 6)
if _total_weight != 1.0:  # fail loudly at import rather than skew every candidate
    raise ValueError(f"Scoring weights must sum to 1.0, got {_total_weight}. Check your .env.")

IMPORTANCE_WEIGHTS = {
    "required": settings.importance_weight_required,
    "preferred": settings.importance_weight_preferred,
    "nice_to_have": settings.importance_weight_nice_to_have,
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Per-skill assessment
# --------------------------------------------------------------------------- #


@dataclass
class SkillAssessment:
    skill: str
    category: str
    importance: str
    status: str
    score: float
    confidence: str
    evidence: dict
    rationale: str

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "category": self.category,
            "importance": self.importance,
            "status": self.status,
            "match": {
                STATUS_STRONG: "Strong Match",
                STATUS_PARTIAL: "Partial Match",
                STATUS_WEAK: "Weak Match",
                STATUS_MISSING: "Not Demonstrated",
                STATUS_UNKNOWN: "Unknown / No Public Evidence",
            }[self.status],
            "score": round(self.score, 1),
            "confidence": self.confidence,
            "evidence": self.evidence,
            "rationale": self.rationale,
        }


def _peer_coverage(skill: dict, requirements: JobRequirements, evidence_by_skill: dict[str, ev.Evidence]) -> int:
    """How many *other* skills in the same category the candidate does evidence.

    This is what licenses a MISSING verdict: if a candidate demonstrates three
    other databases and not this one, the absence is informative. If we have no
    signal in the category at all, absence tells us nothing.
    """
    category = skill.get("category")
    count = 0
    for other in requirements.skills:
        if other["name"] == skill["name"] or other.get("category") != category:
            continue
        other_evidence = evidence_by_skill.get(other["name"])
        if other_evidence and (other_evidence.in_resume or other_evidence.in_github):
            count += 1
    return count


def classify_skill(
    evidence: ev.Evidence,
    peer_coverage: int,
    category: str,
    resume_is_substantive: bool,
) -> str:
    """Evidence -> status. Conservative by construction: the default for absence
    is UNKNOWN, and MISSING has to be earned."""
    if evidence.in_resume and evidence.in_github:
        return STATUS_STRONG

    if evidence.in_github:
        # Public code is strong evidence even without a resume mention.
        return STATUS_STRONG if evidence.github_repo_count >= 2 or evidence.github_code_share >= 15 else STATUS_PARTIAL

    if evidence.in_resume:
        return STATUS_PARTIAL if evidence.resume_is_usage else STATUS_WEAK

    # No evidence anywhere. Only call it missing when the silence is meaningful:
    # practices are rarely evidenced publicly, so they stay unknown.
    if category != ev.PRACTICE_CATEGORY and peer_coverage >= 2 and resume_is_substantive:
        return STATUS_MISSING

    return STATUS_UNKNOWN


def score_skill(status: str, evidence: ev.Evidence) -> float:
    """Status -> 0-100, with a bonus for depth of evidence."""
    if status == STATUS_STRONG:
        depth = min(15.0, 3.0 * evidence.github_repo_count + (5.0 if evidence.resume_is_usage else 0.0))
        return clamp(85.0 + depth)
    if status == STATUS_PARTIAL:
        depth = min(15.0, 4.0 * evidence.github_repo_count + (6.0 if evidence.resume_is_usage else 0.0))
        return clamp(58.0 + depth)
    if status == STATUS_WEAK:
        return 30.0
    return 0.0  # missing and unknown alike contribute nothing to the numerator


def confidence_label(evidence: ev.Evidence, status: str) -> str:
    if status == STATUS_UNKNOWN:
        return "Low"
    if evidence.in_resume and evidence.in_github:
        return "High"
    if evidence.github_repo_count >= 2 or evidence.resume_is_usage:
        return "Medium"
    return "Low"


def _rationale(status: str, evidence: ev.Evidence, skill_name: str) -> str:
    if status == STATUS_STRONG:
        return f"{skill_name} appears in both the resume and public GitHub work."
    if status == STATUS_PARTIAL and evidence.in_github:
        return f"{skill_name} is evidenced in public repositories but not stated in the resume."
    if status == STATUS_PARTIAL:
        return f"{skill_name} is described as used in the resume, without independent public evidence."
    if status == STATUS_WEAK:
        return f"{skill_name} is listed in the resume's skills section with no described usage."
    if status == STATUS_MISSING:
        return (
            f"No evidence of {skill_name}, while comparable skills in the same category are "
            "evidenced — the absence appears informative."
        )
    return (
        f"No public evidence of {skill_name} either way. This is a verification gap to "
        "raise in interview, not a demonstrated gap."
    )


def assess_skills(requirements: JobRequirements, resume: dict, analysis: dict) -> list[SkillAssessment]:
    evidence_by_skill = {
        skill["name"]: ev.gather(skill["name"], resume, analysis) for skill in requirements.skills
    }

    # A near-empty resume makes silence uninformative, so MISSING is withheld.
    resume_is_substantive = bool(resume.get("experience")) or len(resume.get("projects") or []) >= 2

    assessments: list[SkillAssessment] = []
    for skill in requirements.skills:
        evidence = evidence_by_skill[skill["name"]]
        status = classify_skill(
            evidence,
            _peer_coverage(skill, requirements, evidence_by_skill),
            skill.get("category", "tool"),
            resume_is_substantive,
        )
        assessments.append(
            SkillAssessment(
                skill=skill["name"],
                category=skill.get("category", "tool"),
                importance=skill.get("importance", "required"),
                status=status,
                score=score_skill(status, evidence),
                confidence=confidence_label(evidence, status),
                evidence=evidence.to_dict(),
                rationale=_rationale(status, evidence, skill["name"]),
            )
        )
    return assessments


# --------------------------------------------------------------------------- #
# Category scores
# --------------------------------------------------------------------------- #


def weighted_skill_score(assessments: list[SkillAssessment]) -> tuple[float, dict]:
    """Importance-weighted mean, with unknowns at half denominator weight."""
    if not assessments:
        return 0.0, {"skills_counted": 0, "note": "No requirements in this category."}

    numerator = 0.0
    denominator = 0.0
    for item in assessments:
        weight = IMPORTANCE_WEIGHTS.get(item.importance, 1.0)
        effective = weight * (settings.unknown_denominator_weight if item.status == STATUS_UNKNOWN else 1.0)
        numerator += weight * item.score
        denominator += effective * 100.0

    score = clamp(100.0 * numerator / denominator) if denominator else 0.0
    return score, {
        "skills_counted": len(assessments),
        "unknowns": sum(1 for item in assessments if item.status == STATUS_UNKNOWN),
        "formula": "importance-weighted mean of skill scores; unknowns at half denominator weight",
    }


def score_experience(requirements: JobRequirements, resume: dict) -> tuple[float, dict]:
    """Years against the requirement, blended with domain overlap."""
    months = resume.get("total_experience_months")
    if months is None:
        months = sum(
            int(role.get("duration_months") or 0)
            for role in resume.get("experience") or []
            if isinstance(role.get("duration_months"), (int, float))
        ) or None

    required_years = requirements.min_years_experience
    detail: dict = {"evidenced_months": months, "required_years": required_years}

    if months is None:
        # No dates to work with — neutral rather than punitive, flagged instead.
        years_score = 55.0
        detail["note"] = "Duration not stated in the resume; scored neutrally and reflected in confidence."
    elif not required_years:
        years_score = 80.0 if months > 0 else 40.0
        detail["note"] = "The JD states no minimum experience."
    else:
        ratio = (months / 12.0) / required_years
        years_score = clamp(100.0 * min(1.0, ratio))
        detail["ratio"] = round(ratio, 2)

    domains = requirements.experience_domains or requirements.domain_knowledge
    if domains:
        haystack = " ".join(
            [
                str(role.get("role") or "") + " " + str(role.get("description") or "")
                for role in resume.get("experience") or []
            ]
            + [str(project.get("description") or "") for project in resume.get("projects") or []]
            + [str(resume.get("summary") or "")]
        )
        matched = [domain for domain in domains if ev._mentions(haystack, ev.variants(domain))]
        domain_score = 100.0 * len(matched) / len(domains)
        detail["domains_required"] = domains
        detail["domains_evidenced"] = matched
        score = 0.6 * years_score + 0.4 * domain_score
    else:
        score = years_score

    detail["score"] = round(score, 1)
    return clamp(score), detail


def score_education(requirements: JobRequirements, resume: dict) -> tuple[float, dict]:
    entries = resume.get("education") or []
    required = requirements.education_min_level

    detail: dict = {"required_level": required, "entries": len(entries)}

    if not required or required == "none":
        detail["note"] = "The JD states no education requirement."
        return (100.0 if entries else 80.0), detail

    def level_index(value: str | None) -> int:
        try:
            return EDUCATION_LEVELS.index(str(value or "").lower())
        except ValueError:
            return -1

    candidate_best = max((level_index(entry.get("level")) for entry in entries), default=-1)
    required_index = level_index(required)
    detail["highest_level"] = EDUCATION_LEVELS[candidate_best] if candidate_best >= 0 else None

    if candidate_best < 0:
        detail["note"] = "Education level could not be determined from the resume."
        return 50.0, detail  # unknown, not a failure

    gap = required_index - candidate_best
    base = 100.0 if gap <= 0 else (70.0 if gap == 1 else 40.0)

    if requirements.education_fields:
        fields_text = " ".join(str(entry.get("field") or "") for entry in entries)
        matched = [f for f in requirements.education_fields if ev._mentions(fields_text, ev.variants(f))]
        detail["fields_required"] = requirements.education_fields
        detail["fields_matched"] = matched
        if not matched:
            base = max(40.0, base - 15.0)

    detail["score"] = round(base, 1)
    return clamp(base), detail


def score_practices(requirements: JobRequirements, resume: dict, analysis: dict) -> tuple[float, dict]:
    """Engineering hygiene, evidenced by repository facts rather than claims."""
    signals = ev.practice_evidence(analysis)

    components = {
        "documentation": clamp(signals["documentation_subscore"]),
        "testing": clamp(signals["testing_subscore"]),
        "consistency": clamp(signals["consistency_subscore"]),
        "licensing": clamp(100.0 * signals["license_ratio"]),
    }
    score = (
        0.30 * components["documentation"]
        + 0.30 * components["testing"]
        + 0.25 * components["consistency"]
        + 0.15 * components["licensing"]
    )

    practice_skills = [
        skill for skill in requirements.skills if skill.get("category") == ev.PRACTICE_CATEGORY
    ]
    detail = {
        "components": {key: round(value, 1) for key, value in components.items()},
        "repos_considered": signals["repos_considered"],
        "practices_requested": [skill["name"] for skill in practice_skills],
        "formula": "0.30·docs + 0.30·tests + 0.25·commit consistency + 0.15·licensing",
    }

    if signals["repos_considered"] == 0:
        detail["note"] = "No active public repositories; practices could not be evidenced."
        return 50.0, detail

    detail["score"] = round(score, 1)
    return clamp(score), detail


# --------------------------------------------------------------------------- #
# Overall
# --------------------------------------------------------------------------- #


def recommendation_for(score: float) -> str:
    for threshold, label in RECOMMENDATION_BANDS:
        if score >= threshold:
            return label
    return "Poor Fit"


def compute_confidence(assessments: list[SkillAssessment], resume: dict, analysis: dict, jd_skill_count: int) -> tuple[float, dict]:
    """How much the inputs justify trusting the score. Separate from the score
    itself on purpose: a confident 60 and a shaky 60 mean different things."""
    penalties: list[dict] = []
    confidence = 100.0

    if assessments:
        unknown_fraction = sum(1 for item in assessments if item.status == STATUS_UNKNOWN) / len(assessments)
        penalty = 40.0 * unknown_fraction
        confidence -= penalty
        penalties.append({
            "reason": f"{unknown_fraction:.0%} of requirements have no public evidence either way",
            "penalty": round(penalty, 1),
        })

    repo_count = len(analysis.get("repositories") or [])
    if repo_count < 3:
        penalty = 20.0 if repo_count == 0 else 10.0
        confidence -= penalty
        penalties.append({"reason": f"Only {repo_count} public repositories to draw on", "penalty": penalty})

    if not resume.get("experience"):
        confidence -= 10.0
        penalties.append({"reason": "No work experience found in the resume", "penalty": 10.0})

    if resume.get("total_experience_months") is None:
        confidence -= 5.0
        penalties.append({"reason": "Resume does not state durations, so experience is estimated", "penalty": 5.0})

    if jd_skill_count < 5:
        confidence -= 10.0
        penalties.append({"reason": "The job description lists few concrete requirements", "penalty": 10.0})

    return clamp(confidence, 20.0, 99.0), {"penalties": penalties}


def compute_match(
    requirements: JobRequirements,
    resume: dict,
    analysis: dict,
    project_relevance: list[dict],
) -> dict:
    """The whole deterministic calculation. `project_relevance` is computed
    separately (it needs embeddings) and passed in as data."""
    assessments = assess_skills(requirements, resume, analysis)

    technical = [item for item in assessments if item.category in TECHNICAL_CATEGORIES]
    tooling = [item for item in assessments if item.category in TOOLING_CATEGORIES]

    technical_score, technical_detail = weighted_skill_score(technical)
    tooling_score, tooling_detail = weighted_skill_score(tooling)
    experience_score, experience_detail = score_experience(requirements, resume)
    education_score, education_detail = score_education(requirements, resume)
    practices_score, practices_detail = score_practices(requirements, resume, analysis)

    top_projects = sorted(project_relevance, key=lambda item: item["relevance"], reverse=True)[:3]
    project_score = sum(item["relevance"] for item in top_projects) / len(top_projects) if top_projects else 0.0

    categories = {
        "technical_skills": (technical_score, technical_detail),
        "work_experience": (experience_score, experience_detail),
        "project_relevance": (project_score, {"projects_considered": len(project_relevance),
                                              "formula": "mean relevance of the three most relevant projects"}),
        "tools_frameworks": (tooling_score, tooling_detail),
        "education": (education_score, education_detail),
        "engineering_practices": (practices_score, practices_detail),
    }

    overall = sum(score * WEIGHTS[name] for name, (score, _) in categories.items())
    confidence, confidence_detail = compute_confidence(assessments, resume, analysis, len(requirements.skills))

    breakdown = {
        name: {
            "score": round(score, 1),
            "weight_percent": round(WEIGHTS[name] * 100, 1),
            "contribution": round(score * WEIGHTS[name], 2),
            "detail": detail,
        }
        for name, (score, detail) in categories.items()
    }

    return {
        "overall_match": round(clamp(overall), 1),
        "confidence": round(confidence, 1),
        "recommendation": recommendation_for(clamp(overall)),
        "score_breakdown": breakdown,
        "confidence_breakdown": confidence_detail,
        "skill_analysis": [item.to_dict() for item in assessments],
        "strong_matches": [item.skill for item in assessments if item.status == STATUS_STRONG],
        "partial_matches": [item.skill for item in assessments if item.status == STATUS_PARTIAL],
        "weak_matches": [item.skill for item in assessments if item.status == STATUS_WEAK],
        "missing_skills": [item.skill for item in assessments if item.status == STATUS_MISSING],
        "unknown_skills": [item.skill for item in assessments if item.status == STATUS_UNKNOWN],
        "project_analysis": sorted(project_relevance, key=lambda item: item["relevance"], reverse=True),
        "experience_analysis": experience_detail,
    }


# --------------------------------------------------------------------------- #
# Discrepancies
# --------------------------------------------------------------------------- #


def detect_discrepancies(assessments: list[SkillAssessment], analysis: dict) -> list[dict]:
    """Where the two sources disagree.

    Framed as verification gaps in both directions, never as accusations: public
    GitHub activity is a partial view of anyone's work, and plenty of real
    experience is behind a company firewall.
    """
    discrepancies: list[dict] = []
    public_repo_count = len(analysis.get("repositories") or [])

    for item in assessments:
        evidence = item.evidence
        resume_hits = evidence.get("resume") or []
        github_hits = evidence.get("github") or []

        # Claimed in the resume as used, but nothing public corroborates it.
        if resume_hits and evidence.get("resume_is_usage") and not github_hits and public_repo_count >= 5:
            discrepancies.append({
                "type": "verification_gap",
                "skill": item.skill,
                "severity": "medium" if item.importance == "required" else "low",
                "summary": (
                    f"The resume describes using {item.skill}, but the public GitHub profile does not "
                    f"independently verify it."
                ),
                "resume_evidence": resume_hits,
                "github_evidence": [],
                "note": (
                    "This is an evidence discrepancy, not a contradiction. Professional work is "
                    "frequently private, so absence from GitHub is expected in many cases. Worth "
                    "confirming in interview."
                ),
            })

        # Public work shows it, the resume does not mention it.
        if github_hits and not resume_hits and (
            evidence.get("github_repo_count", 0) >= 1 or evidence.get("github_code_share", 0) >= 5
        ):
            discrepancies.append({
                "type": "additional_evidence",
                "skill": item.skill,
                "severity": "informational",
                "summary": (
                    f"Public GitHub work evidences {item.skill}, but the resume does not mention it — "
                    f"the candidate may be underselling this."
                ),
                "resume_evidence": [],
                "github_evidence": github_hits,
                "note": "GitHub supplies evidence the resume does not represent.",
            })

    return discrepancies
