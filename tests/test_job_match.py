"""Tests for the JD + resume + GitHub matching feature.

No network, no API keys: PDFs are generated in-memory with PyMuPDF, and the LLM
is replaced with a stub that returns fixed JSON. The scoring engine needs no
stub at all — it is pure Python, which is the whole point of separating it from
the model.
"""

import io
import json

import pytest

from app.services import evidence as ev
from app.services import jd_parser, job_match, match_engine, resume_parser
from app.services.jd_parser import JobRequirements
from app.services.match_engine import (
    STATUS_MISSING,
    STATUS_PARTIAL,
    STATUS_STRONG,
    STATUS_UNKNOWN,
    STATUS_WEAK,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

RESUME_TEXT = """Priya Raman
Email: priya@example.com | Phone: +91 98765 43210
Gender: Female
Date of Birth: 12/04/1999

SUMMARY
Backend engineer with 2 years building Python services.

EXPERIENCE
Backend Engineer, Zeta Systems (Jan 2023 - Jan 2025)
Built FastAPI services backed by PostgreSQL. Deployed on AWS.

SKILLS
Python, FastAPI, PostgreSQL, Docker, Redis

PROJECTS
Face Recognition Pipeline - OpenCV and PyTorch based recognition system.
"""


def make_pdf(text: str = RESUME_TEXT) -> bytes:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((60, 70), text, fontsize=9)
    data = document.tobytes()
    document.close()
    return data


STRUCTURED_RESUME = {
    "name": "Priya Raman",
    "summary": "Backend engineer with 2 years building Python services.",
    "education": [{"degree": "B.Tech", "field": "Computer Science", "institution": "IIT", "level": "bachelors"}],
    "experience": [{
        "role": "Backend Engineer", "company": "Zeta Systems", "type": "job",
        "duration_months": 24, "description": "Built FastAPI services backed by PostgreSQL on AWS.",
        "technologies": ["Python", "FastAPI", "PostgreSQL", "AWS"],
    }],
    "skills": {
        "languages": ["Python"], "frameworks": ["FastAPI"], "databases": ["PostgreSQL", "Redis"],
        "cloud": ["AWS"], "tools": ["Docker"], "other": [],
    },
    "skill_mentions": [
        {"skill": "Python", "contexts": ["skills_section", "experience:Zeta Systems"]},
        {"skill": "FastAPI", "contexts": ["skills_section", "experience:Zeta Systems"]},
        {"skill": "Docker", "contexts": ["skills_section"]},
        {"skill": "PyTorch", "contexts": ["project:Face Recognition Pipeline"]},
    ],
    "certifications": [],
    "projects": [{
        "name": "Face Recognition Pipeline",
        "description": "OpenCV and PyTorch based recognition system.",
        "technologies": ["OpenCV", "PyTorch", "Python"], "achievements": [],
    }],
    "achievements": [],
    "total_experience_months": 24,
    "redacted_categories": [],
    "parse_warnings": [],
}

GITHUB_ANALYSIS = {
    "profile": {"github_username": "priya", "public_repos": 6, "followers": 40},
    "repositories": [
        {"name": "face-recognition", "primary_language": "Python", "languages": {"Python": 40000},
         "topics": ["opencv", "pytorch", "computer-vision"], "stars": 120, "forks": 10,
         "is_archived": False, "has_readme": True, "has_license": True},
        {"name": "fastapi-billing", "primary_language": "Python", "languages": {"Python": 22000},
         "topics": ["fastapi", "postgresql", "pytest"], "stars": 30, "forks": 4,
         "is_archived": False, "has_readme": True, "has_license": False},
        {"name": "dotfiles", "primary_language": "Shell", "languages": {"Shell": 3000},
         "topics": [], "stars": 2, "forks": 0,
         "is_archived": False, "has_readme": False, "has_license": False},
    ],
    "languages": {
        "distribution_percent": {"Python": 92.3, "Shell": 7.7},
        "primary_language": "Python",
        "ai_ml_ecosystem_detected": ["pytorch", "opencv"],
    },
    "activity": {"longest_streak_weeks": 12, "inactive_periods": []},
    "developer_score": {"overall_score": 71.0, "consistency": 70.0, "popularity": 60.0,
                        "code_diversity": 55.0, "documentation": 66.0, "testing": 33.0},
}


def requirements(**overrides) -> JobRequirements:
    base = JobRequirements(
        role_title="Backend Engineer",
        skills=[
            {"name": "Python", "category": "language", "importance": "required", "reason": None},
            {"name": "FastAPI", "category": "framework", "importance": "required", "reason": None},
            {"name": "PostgreSQL", "category": "database", "importance": "required", "reason": None},
            {"name": "Docker", "category": "tool", "importance": "preferred", "reason": None},
            {"name": "CUDA", "category": "language", "importance": "preferred", "reason": None},
        ],
        responsibilities=["Build and operate backend services"],
        min_years_experience=2,
        education_min_level="bachelors",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# --------------------------------------------------------------------------- #
# 1. PDF extraction and validation
# --------------------------------------------------------------------------- #


def test_extracts_text_from_a_real_pdf():
    text = resume_parser.extract_text(make_pdf())
    assert "Backend Engineer" in text
    assert "FastAPI" in text


def test_rejects_non_pdf_bytes():
    with pytest.raises(resume_parser.InvalidPDFError):
        resume_parser.validate_upload(b"just some text", content_type="text/plain", filename="cv.txt")


def test_rejects_empty_upload():
    with pytest.raises(resume_parser.InvalidPDFError):
        resume_parser.validate_upload(b"")


def test_rejects_oversized_upload(monkeypatch):
    monkeypatch.setattr(resume_parser.settings, "resume_max_bytes", 100)
    with pytest.raises(resume_parser.ResumeTooLargeError):
        resume_parser.validate_upload(b"%PDF-" + b"x" * 500)


def test_rejects_a_pdf_with_a_lying_content_type():
    with pytest.raises(resume_parser.InvalidPDFError):
        resume_parser.validate_upload(make_pdf(), content_type="image/png", filename="cv.pdf")


def test_accepts_a_valid_pdf():
    resume_parser.validate_upload(make_pdf(), content_type="application/pdf", filename="cv.pdf")


def test_empty_pdf_raises_rather_than_returning_blank():
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf
    document = pymupdf.open()
    document.new_page()
    blank = document.tobytes()
    document.close()

    with pytest.raises(resume_parser.EmptyResumeError):
        resume_parser.extract_text(blank)


def test_corrupt_pdf_gives_a_useful_error():
    with pytest.raises(resume_parser.InvalidPDFError):
        resume_parser.extract_text(b"%PDF-1.4 this is not really a pdf")


# --------------------------------------------------------------------------- #
# 2. Fairness: protected characteristics never reach the model
# --------------------------------------------------------------------------- #


def test_scrubs_protected_characteristics():
    cleaned, removed = resume_parser.scrub_protected_content(RESUME_TEXT)
    assert "Gender" not in cleaned
    assert "Date of Birth" not in cleaned
    assert "protected characteristics" in removed


def test_redacts_contact_details():
    cleaned, removed = resume_parser.scrub_protected_content(RESUME_TEXT)
    assert "priya@example.com" not in cleaned
    assert "98765" not in cleaned
    assert "contact details" in removed


def test_scrubbing_keeps_the_professional_content():
    cleaned, _ = resume_parser.scrub_protected_content(RESUME_TEXT)
    for keyword in ("Backend Engineer", "FastAPI", "PostgreSQL", "Face Recognition"):
        assert keyword in cleaned


def test_narration_context_carries_no_identity():
    computed = match_engine.compute_match(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS, [])
    context = job_match._narration_context(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS, computed)
    assert "Priya" not in context
    assert "example.com" not in context


# --------------------------------------------------------------------------- #
# 3. JD parsing
# --------------------------------------------------------------------------- #


def test_jd_normalises_categories_and_importance():
    parsed = jd_parser._coerce({
        "role_title": "ML Engineer",
        "skills": [
            {"name": "Python", "category": "language", "importance": "REQUIRED"},
            {"name": "CUDA", "category": "nonsense", "importance": "nice to have"},
            {"name": "", "category": "language", "importance": "required"},
        ],
        "min_years_experience": "3",
        "education_min_level": "Masters",
    })
    assert parsed.role_title == "ML Engineer"
    assert len(parsed.skills) == 2                    # the nameless one is dropped
    assert parsed.skills[1]["category"] == "tool"     # unknown category falls back
    assert parsed.skills[1]["importance"] == "nice_to_have"
    assert parsed.min_years_experience == 3.0
    assert parsed.education_min_level == "masters"


def test_jd_deduplicates_skills():
    parsed = jd_parser._coerce({"skills": [
        {"name": "Python", "category": "language", "importance": "required"},
        {"name": "python", "category": "language", "importance": "preferred"},
    ]})
    assert len(parsed.skills) == 1


def test_jd_fingerprint_is_stable_and_content_addressed():
    assert jd_parser.fingerprint("  Hello role  ") == jd_parser.fingerprint("Hello role")
    assert jd_parser.fingerprint("a") != jd_parser.fingerprint("b")


@pytest.mark.asyncio
async def test_jd_rejects_a_too_short_description():
    with pytest.raises(jd_parser.JDError):
        await jd_parser.parse_job_description("Backend dev")


# --------------------------------------------------------------------------- #
# 4. Evidence lookup
# --------------------------------------------------------------------------- #


def test_finds_skill_in_both_sources():
    found = ev.gather("Python", STRUCTURED_RESUME, GITHUB_ANALYSIS)
    assert found.in_resume and found.in_github
    assert found.github_code_share > 90


def test_aliases_match_across_spellings():
    found = ev.gather("Postgres", STRUCTURED_RESUME, GITHUB_ANALYSIS)
    assert found.in_resume       # resume says "PostgreSQL"
    assert found.in_github       # repo topic says "postgresql"


def test_word_boundaries_prevent_false_positives():
    assert not ev._mentions("google cloud", ev.variants("Go"))
    assert not ev._mentions("react native", ev.variants("R"))
    assert ev._mentions("built with Go", ev.variants("Go"))


def test_cpp_and_csharp_do_not_break_the_matcher():
    assert ev._mentions("experience with C++ templates", ev.variants("C++"))
    assert not ev._mentions("C++ only", ev.variants("C#"))


def test_distinguishes_listed_from_used():
    used = ev.resume_evidence("FastAPI", STRUCTURED_RESUME)
    listed = ev.resume_evidence("Docker", STRUCTURED_RESUME)
    assert used.resume_is_usage is True
    assert listed.resume_is_usage is False


def test_evidence_strings_are_specific_enough_to_verify():
    found = ev.github_evidence("PyTorch", STRUCTURED_RESUME | {}, ) if False else ev.github_evidence("PyTorch", GITHUB_ANALYSIS)
    assert any("face-recognition" in item for item in found.github)


# --------------------------------------------------------------------------- #
# 5. Skill classification — missing vs unknown
# --------------------------------------------------------------------------- #


def test_both_sources_is_a_strong_match():
    assessments = {a.skill: a for a in match_engine.assess_skills(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS)}
    assert assessments["Python"].status == STATUS_STRONG
    assert assessments["Python"].confidence == "High"


def test_listed_but_unused_and_unevidenced_is_weak():
    resume = json.loads(json.dumps(STRUCTURED_RESUME))
    requirement = JobRequirements(skills=[
        {"name": "Docker", "category": "tool", "importance": "required"},
    ])
    assessments = match_engine.assess_skills(requirement, resume, GITHUB_ANALYSIS)
    assert assessments[0].status == STATUS_WEAK


def test_github_only_evidence_still_counts():
    resume = json.loads(json.dumps(STRUCTURED_RESUME))
    resume["skills"] = {"languages": [], "frameworks": [], "databases": [], "cloud": [], "tools": [], "other": []}
    resume["skill_mentions"] = []
    resume["projects"] = []
    resume["experience"][0]["technologies"] = []
    resume["experience"][0]["description"] = "Worked on services."

    requirement = JobRequirements(skills=[{"name": "Python", "category": "language", "importance": "required"}])
    assessment = match_engine.assess_skills(requirement, resume, GITHUB_ANALYSIS)[0]
    assert assessment.status == STATUS_STRONG      # 92% of public code
    assert assessment.evidence["resume"] == []


def test_no_evidence_anywhere_is_unknown_not_missing():
    """The headline requirement: CUDA absent from both sources is UNKNOWN."""
    assessments = {a.skill: a for a in match_engine.assess_skills(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS)}
    cuda = assessments["CUDA"]
    assert cuda.status == STATUS_UNKNOWN
    assert cuda.to_dict()["match"] == "Unknown / No Public Evidence"
    assert "verification gap" in cuda.rationale


def test_unknown_is_never_phrased_as_a_deficiency():
    assessments = match_engine.assess_skills(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS)
    for item in assessments:
        if item.status == STATUS_UNKNOWN:
            lowered = item.rationale.lower()
            for phrasing in ("does not know", "lacks the skill", "cannot", "unqualified"):
                assert phrasing not in lowered


def test_missing_requires_peer_coverage_in_the_same_category():
    """Absence only becomes informative when comparable skills ARE evidenced."""
    requirement = JobRequirements(skills=[
        {"name": "PostgreSQL", "category": "database", "importance": "required"},
        {"name": "Redis", "category": "database", "importance": "required"},
        {"name": "Cassandra", "category": "database", "importance": "required"},
    ])
    assessments = {a.skill: a for a in match_engine.assess_skills(requirement, STRUCTURED_RESUME, GITHUB_ANALYSIS)}
    assert assessments["Cassandra"].status == STATUS_MISSING
    assert "absence appears informative" in assessments["Cassandra"].rationale


def test_missing_is_withheld_when_the_resume_is_thin():
    thin = {"skills": {}, "skill_mentions": [], "experience": [], "projects": []}
    requirement = JobRequirements(skills=[
        {"name": "PostgreSQL", "category": "database", "importance": "required"},
        {"name": "Redis", "category": "database", "importance": "required"},
        {"name": "Cassandra", "category": "database", "importance": "required"},
    ])
    assessments = {a.skill: a for a in match_engine.assess_skills(requirement, thin, GITHUB_ANALYSIS)}
    assert assessments["Cassandra"].status == STATUS_UNKNOWN


def test_practices_are_never_marked_missing():
    """Code review habits are rarely publicly evidenced — silence proves nothing."""
    requirement = JobRequirements(skills=[
        {"name": "Unit testing", "category": "practice", "importance": "required"},
        {"name": "Code review", "category": "practice", "importance": "required"},
        {"name": "Pair programming", "category": "practice", "importance": "required"},
    ])
    assessments = match_engine.assess_skills(requirement, STRUCTURED_RESUME, GITHUB_ANALYSIS)
    assert all(item.status != STATUS_MISSING for item in assessments)


# --------------------------------------------------------------------------- #
# 6. Deterministic scoring
# --------------------------------------------------------------------------- #


def test_weights_sum_to_one():
    assert round(sum(match_engine.WEIGHTS.values()), 6) == 1.0


def test_scoring_is_deterministic():
    first = match_engine.compute_match(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS, [])
    second = match_engine.compute_match(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS, [])
    assert first["overall_match"] == second["overall_match"]
    assert first["confidence"] == second["confidence"]


def test_overall_is_the_weighted_sum_of_its_parts():
    report = match_engine.compute_match(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS, [])
    recomputed = sum(block["contribution"] for block in report["score_breakdown"].values())
    assert report["overall_match"] == pytest.approx(recomputed, abs=0.15)


def test_every_category_reports_its_weight_and_contribution():
    report = match_engine.compute_match(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS, [])
    for name, block in report["score_breakdown"].items():
        assert block["weight_percent"] == pytest.approx(match_engine.WEIGHTS[name] * 100)
        assert 0 <= block["score"] <= 100
        assert block["detail"]


@pytest.mark.parametrize("score,expected", [
    (95, "Excellent Fit"), (90, "Excellent Fit"),
    (85, "Strong Fit"), (80, "Strong Fit"),
    (70, "Moderate Fit"), (65, "Moderate Fit"),
    (55, "Weak Fit"), (50, "Weak Fit"),
    (30, "Poor Fit"), (0, "Poor Fit"),
])
def test_recommendation_bands(score, expected):
    assert match_engine.recommendation_for(score) == expected


def test_unknowns_cost_less_than_confirmed_gaps():
    """An unknown skill must dent the score less than a demonstrated absence."""
    unknown_case = [match_engine.SkillAssessment(
        skill="CUDA", category="language", importance="required", status=STATUS_UNKNOWN,
        score=0.0, confidence="Low", evidence={}, rationale="")]
    missing_case = [match_engine.SkillAssessment(
        skill="CUDA", category="language", importance="required", status=STATUS_MISSING,
        score=0.0, confidence="Low", evidence={}, rationale="")]

    strong = match_engine.SkillAssessment(
        skill="Python", category="language", importance="required", status=STATUS_STRONG,
        score=100.0, confidence="High", evidence={}, rationale="")

    with_unknown, _ = match_engine.weighted_skill_score([strong, *unknown_case])
    with_missing, _ = match_engine.weighted_skill_score([strong, *missing_case])
    assert with_unknown > with_missing


def test_unknowns_reduce_confidence():
    all_unknown = [match_engine.SkillAssessment(
        skill=f"S{i}", category="language", importance="required", status=STATUS_UNKNOWN,
        score=0.0, confidence="Low", evidence={}, rationale="") for i in range(5)]
    none_unknown = [match_engine.SkillAssessment(
        skill=f"S{i}", category="language", importance="required", status=STATUS_STRONG,
        score=95.0, confidence="High", evidence={}, rationale="") for i in range(5)]

    low, _ = match_engine.compute_confidence(all_unknown, STRUCTURED_RESUME, GITHUB_ANALYSIS, 5)
    high, _ = match_engine.compute_confidence(none_unknown, STRUCTURED_RESUME, GITHUB_ANALYSIS, 5)
    assert low < high


def test_confidence_explains_every_penalty():
    _, detail = match_engine.compute_confidence(
        match_engine.assess_skills(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS),
        STRUCTURED_RESUME, GITHUB_ANALYSIS, 5,
    )
    for penalty in detail["penalties"]:
        assert penalty["reason"] and penalty["penalty"] > 0


def test_experience_shortfall_scales_the_score():
    short = {**STRUCTURED_RESUME, "total_experience_months": 6}
    full = {**STRUCTURED_RESUME, "total_experience_months": 48}
    low, _ = match_engine.score_experience(requirements(), short)
    high, _ = match_engine.score_experience(requirements(), full)
    assert low < high
    assert high == pytest.approx(100.0, abs=0.1) or high > 80


def test_unstated_duration_is_neutral_not_zero():
    unknown_duration = {**STRUCTURED_RESUME, "total_experience_months": None,
                        "experience": [{"role": "Engineer", "company": "X"}]}
    score, detail = match_engine.score_experience(requirements(), unknown_duration)
    assert 40 <= score <= 70
    assert "confidence" in detail["note"]


def test_education_below_requirement_is_penalised_not_zeroed():
    diploma = {**STRUCTURED_RESUME, "education": [{"level": "diploma", "field": "Computer Science"}]}
    score, _ = match_engine.score_education(requirements(), diploma)
    assert 30 < score < 100


def test_education_unknown_level_is_not_a_failure():
    unknown = {**STRUCTURED_RESUME, "education": [{"degree": "Something", "field": "CS"}]}
    score, detail = match_engine.score_education(requirements(), unknown)
    assert score == 50.0
    assert "could not be determined" in detail["note"]


def test_practices_score_uses_repository_facts():
    score, detail = match_engine.score_practices(requirements(), STRUCTURED_RESUME, GITHUB_ANALYSIS)
    assert 0 <= score <= 100
    assert detail["components"]["documentation"] == 66.0
    assert detail["repos_considered"] == 3


# --------------------------------------------------------------------------- #
# 7. Discrepancy detection
# --------------------------------------------------------------------------- #


def _analysis_with_repos(count: int) -> dict:
    analysis = json.loads(json.dumps(GITHUB_ANALYSIS))
    template = analysis["repositories"][2]
    analysis["repositories"] = [dict(template, name=f"repo{i}") for i in range(count)]
    analysis["languages"]["distribution_percent"] = {"Shell": 100.0}
    analysis["languages"]["ai_ml_ecosystem_detected"] = []
    return analysis


def test_detects_a_resume_claim_github_cannot_verify():
    analysis = _analysis_with_repos(6)
    requirement = JobRequirements(skills=[{"name": "FastAPI", "category": "framework", "importance": "required"}])
    assessments = match_engine.assess_skills(requirement, STRUCTURED_RESUME, analysis)
    found = match_engine.detect_discrepancies(assessments, analysis)

    gaps = [item for item in found if item["type"] == "verification_gap"]
    assert gaps and gaps[0]["skill"] == "FastAPI"


def test_discrepancy_language_does_not_accuse():
    analysis = _analysis_with_repos(6)
    requirement = JobRequirements(skills=[{"name": "FastAPI", "category": "framework", "importance": "required"}])
    assessments = match_engine.assess_skills(requirement, STRUCTURED_RESUME, analysis)
    gap = match_engine.detect_discrepancies(assessments, analysis)[0]

    combined = (gap["summary"] + gap["note"]).lower()
    for accusation in ("lying", "false", "dishonest", "exaggerat", "fabricat", "overstat"):
        assert accusation not in combined
    assert "not independently verify" in gap["summary"] or "does not" in gap["summary"]


def test_detects_github_evidence_absent_from_the_resume():
    resume = json.loads(json.dumps(STRUCTURED_RESUME))
    resume["skill_mentions"] = []
    resume["projects"] = []
    resume["skills"] = {"languages": ["Python"], "frameworks": [], "databases": [], "cloud": [], "tools": [], "other": []}

    requirement = JobRequirements(skills=[{"name": "OpenCV", "category": "framework", "importance": "preferred"}])
    assessments = match_engine.assess_skills(requirement, resume, GITHUB_ANALYSIS)
    found = match_engine.detect_discrepancies(assessments, GITHUB_ANALYSIS)

    extra = [item for item in found if item["type"] == "additional_evidence"]
    assert extra and extra[0]["skill"] == "OpenCV"
    assert "underselling" in extra[0]["summary"]


def test_no_discrepancy_when_evidence_agrees():
    requirement = JobRequirements(skills=[{"name": "Python", "category": "language", "importance": "required"}])
    assessments = match_engine.assess_skills(requirement, STRUCTURED_RESUME, GITHUB_ANALYSIS)
    assert match_engine.detect_discrepancies(assessments, GITHUB_ANALYSIS) == []


def test_thin_github_profile_does_not_trigger_verification_gaps():
    """With almost no public code, absence is expected and not worth flagging."""
    analysis = _analysis_with_repos(2)
    requirement = JobRequirements(skills=[{"name": "FastAPI", "category": "framework", "importance": "required"}])
    assessments = match_engine.assess_skills(requirement, STRUCTURED_RESUME, analysis)
    found = match_engine.detect_discrepancies(assessments, analysis)
    assert not [item for item in found if item["type"] == "verification_gap"]


# --------------------------------------------------------------------------- #
# 8. Project relevance
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_relevant_projects_outrank_irrelevant_ones():
    vision_jd = JobRequirements(
        role_title="Computer Vision Engineer",
        skills=[
            {"name": "OpenCV", "category": "framework", "importance": "required"},
            {"name": "PyTorch", "category": "framework", "importance": "required"},
            {"name": "Computer Vision", "category": "domain", "importance": "required"},
        ],
        responsibilities=["Build image recognition pipelines"],
    )
    analysis = json.loads(json.dumps(GITHUB_ANALYSIS))
    analysis["repositories"].append({
        "name": "calculator", "primary_language": "Python", "languages": {"Python": 900},
        "topics": [], "stars": 1, "forks": 0, "is_archived": False,
        "has_readme": False, "has_license": False,
    })

    ranked = await job_match.score_project_relevance(vision_jd, STRUCTURED_RESUME, analysis)
    by_name = {item["project"]: item["relevance"] for item in ranked}

    assert by_name["face-recognition"] > by_name["calculator"]
    assert by_name["face-recognition"] > 50
    assert by_name["calculator"] < 40


@pytest.mark.asyncio
async def test_project_relevance_cites_which_requirements_matched():
    vision_jd = JobRequirements(skills=[
        {"name": "OpenCV", "category": "framework", "importance": "required"},
        {"name": "PyTorch", "category": "framework", "importance": "required"},
    ])
    ranked = await job_match.score_project_relevance(vision_jd, STRUCTURED_RESUME, GITHUB_ANALYSIS)
    top = ranked[0]
    assert top["matched_requirements"]
    assert 0 <= top["relevance"] <= 100


@pytest.mark.asyncio
async def test_resume_projects_are_ranked_alongside_github_ones():
    jd = JobRequirements(skills=[{"name": "PyTorch", "category": "framework", "importance": "required"}])
    ranked = await job_match.score_project_relevance(jd, STRUCTURED_RESUME, GITHUB_ANALYSIS)
    assert {"github", "resume"} <= {item["source"] for item in ranked}


@pytest.mark.asyncio
async def test_archived_repositories_are_excluded():
    analysis = json.loads(json.dumps(GITHUB_ANALYSIS))
    analysis["repositories"][0]["is_archived"] = True
    jd = JobRequirements(skills=[{"name": "OpenCV", "category": "framework", "importance": "required"}])
    ranked = await job_match.score_project_relevance(jd, STRUCTURED_RESUME, analysis)
    assert "face-recognition" not in {item["project"] for item in ranked}


# --------------------------------------------------------------------------- #
# 9. End-to-end orchestration (LLM stubbed)
# --------------------------------------------------------------------------- #


class _StubLLM:
    """Returns whichever canned payload matches the prompt being sent."""

    calls: list = []

    class chat:
        class completions:
            @staticmethod
            async def create(**kwargs):
                _StubLLM.calls.append(kwargs)
                system = kwargs["messages"][0]["content"]

                if "extract structured requirements from a job description" in system:
                    payload = {
                        "role_title": "Backend Engineer",
                        "skills": [
                            {"name": "Python", "category": "language", "importance": "required"},
                            {"name": "FastAPI", "category": "framework", "importance": "required"},
                            {"name": "PostgreSQL", "category": "database", "importance": "required"},
                            {"name": "CUDA", "category": "language", "importance": "preferred"},
                        ],
                        "responsibilities": ["Build backend services"],
                        "min_years_experience": 2,
                        "education_min_level": "bachelors",
                    }
                elif "You extract structured data from a resume" in system:
                    payload = STRUCTURED_RESUME
                else:
                    payload = {
                        "explanation": "Strong Python and FastAPI evidence in both sources.",
                        "strengths": ["Python evidenced across six repositories"],
                        "concerns": ["No public evidence of CUDA either way"],
                        "interview_questions": [
                            {"category": "project", "question": "Walk me through the face-recognition pipeline.",
                             "why": "Their most relevant public project."},
                            {"category": "skill_gap", "question": "Have you worked with CUDA anywhere private?",
                             "why": "No public evidence either way."},
                        ],
                        "learning_recommendations": [
                            {"skill": "CUDA", "why": "Listed as preferred in the JD",
                             "steps": ["CUDA fundamentals", "Memory hierarchy", "Write a kernel"]},
                        ],
                    }

                class Message:
                    content = json.dumps(payload)

                class Choice:
                    message = Message()

                class Response:
                    choices = [Choice()]

                return Response()


@pytest.fixture
def stub_llm(monkeypatch):
    _StubLLM.calls = []
    monkeypatch.setattr("app.services.ai_engine.get_client", lambda: _StubLLM)
    return _StubLLM


@pytest.mark.asyncio
async def test_structure_resume_maps_llm_output_and_records_redactions(stub_llm):
    profile = await resume_parser.structure_resume(RESUME_TEXT)
    assert profile.name == "Priya Raman"
    assert "protected characteristics" in profile.redacted_categories
    assert "Python" in profile.all_skills()

    sent = stub_llm.calls[0]["messages"][1]["content"]
    assert "Gender" not in sent and "priya@example.com" not in sent


@pytest.mark.asyncio
async def test_full_run_produces_every_required_section(stub_llm, monkeypatch):
    async def fake_analyze(username):
        return GITHUB_ANALYSIS

    monkeypatch.setattr(job_match.pipeline, "collect_and_analyze", fake_analyze)

    report = await job_match.run_job_match(
        username="priya", company="Acme",
        job_description="We need a backend engineer with Python, FastAPI and PostgreSQL. " * 3,
        resume=STRUCTURED_RESUME,
    )

    for key in ("overall_match", "confidence", "recommendation", "score_breakdown",
                "strong_matches", "partial_matches", "missing_skills", "unknown_skills",
                "skill_analysis", "project_analysis", "experience_analysis",
                "evidence_discrepancies", "interview_questions", "learning_recommendations",
                "methodology", "disclaimer"):
        assert key in report, f"missing {key}"

    assert 0 <= report["overall_match"] <= 100
    assert report["recommendation"] in {"Excellent Fit", "Strong Fit", "Moderate Fit", "Weak Fit", "Poor Fit"}
    assert "CUDA" in report["unknown_skills"]
    assert "not be the sole basis" in report["disclaimer"]


@pytest.mark.asyncio
async def test_report_survives_a_narration_failure(stub_llm, monkeypatch):
    async def fake_analyze(username):
        return GITHUB_ANALYSIS

    async def exploding_narration(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(job_match.pipeline, "collect_and_analyze", fake_analyze)
    monkeypatch.setattr(job_match, "generate_narration", exploding_narration)

    report = await job_match.run_job_match(
        username="priya", company="Acme",
        job_description="Backend engineer needed with Python, FastAPI and PostgreSQL experience. " * 3,
        resume=STRUCTURED_RESUME,
    )
    assert report["overall_match"] > 0          # deterministic half still stands
    assert report["interview_questions"] == []


@pytest.mark.asyncio
async def test_narration_cannot_change_the_score(stub_llm, monkeypatch):
    """The model is handed the computed numbers; it must not be able to move them."""
    async def fake_analyze(username):
        return GITHUB_ANALYSIS

    async def lying_narration(*args, **kwargs):
        return {"explanation": "Actually a 99% match.", "strengths": [], "concerns": [],
                "interview_questions": [], "learning_recommendations": []}

    monkeypatch.setattr(job_match.pipeline, "collect_and_analyze", fake_analyze)

    jd = "Backend engineer with Python, FastAPI and PostgreSQL. " * 3
    baseline = await job_match.run_job_match("priya", "Acme", jd, STRUCTURED_RESUME)

    monkeypatch.setattr(job_match, "generate_narration", lying_narration)
    with_lies = await job_match.run_job_match("priya", "Acme", jd, STRUCTURED_RESUME)

    assert with_lies["overall_match"] == baseline["overall_match"]


# --------------------------------------------------------------------------- #
# 10. The API endpoint (real routing, real validation, SQLite + stubbed LLM)
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client(monkeypatch, tmp_path, stub_llm):
    """An httpx client bound to the real ASGI app, on a throwaway SQLite DB."""
    import importlib
    import os

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/api.db"

    from app.core import config
    config.get_settings.cache_clear()

    from app.db import session as db_session
    importlib.reload(db_session)

    from app.services import cache as cache_module

    store: dict = {}

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, value, ttl=None):
        store[key] = json.loads(json.dumps(value, default=str))

    monkeypatch.setattr(cache_module, "cache_get", fake_get)
    monkeypatch.setattr(cache_module, "cache_set", fake_set)

    import app.main as main_module
    importlib.reload(main_module)

    monkeypatch.setattr("app.services.pipeline.cache_get", fake_get)
    monkeypatch.setattr("app.services.pipeline.cache_set", fake_set)

    async def fake_analyze(username):
        if username == "ghost":
            from app.services.pipeline import DeveloperNotFoundError
            raise DeveloperNotFoundError(username)
        return GITHUB_ANALYSIS

    monkeypatch.setattr("app.services.job_match.pipeline.collect_and_analyze", fake_analyze)

    from httpx import ASGITransport, AsyncClient

    await db_session.init_db()
    async with AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as async_client:
        yield async_client

    config.get_settings.cache_clear()


async def _token(client) -> str:
    response = await client.post("/auth/register", json={"username": "recruiter", "password": "pw12345"})
    if response.status_code >= 400:
        response = await client.post(
            "/auth/login", data={"username": "recruiter", "password": "pw12345"}
        )
    return response.json()["access_token"]


JD_TEXT = (
    "We are hiring a Backend Engineer to build and operate Python services. "
    "Required: Python, FastAPI, PostgreSQL. Preferred: CUDA. "
    "Bachelor's degree and 2+ years of experience required."
)


@pytest.mark.asyncio
async def test_endpoint_requires_authentication(client):
    response = await client.post(
        "/job-match",
        data={"username": "priya", "company": "Acme", "job_description": JD_TEXT},
        files={"resume_pdf": ("cv.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_returns_a_full_report(client):
    token = await _token(client)
    response = await client.post(
        "/job-match",
        headers={"Authorization": f"Bearer {token}"},
        data={"username": "priya", "company": "Acme", "job_description": JD_TEXT},
        files={"resume_pdf": ("cv.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert 0 <= body["overall_match"] <= 100
    assert 20 <= body["confidence"] <= 99
    assert body["recommendation"] in {"Excellent Fit", "Strong Fit", "Moderate Fit", "Weak Fit", "Poor Fit"}
    assert set(body["score_breakdown"]) == set(match_engine.WEIGHTS)
    assert body["skill_analysis"]
    assert "CUDA" in body["unknown_skills"]
    assert body["disclaimer"]

    # The response must never carry the candidate's identity or contact details.
    serialised = json.dumps(body)
    assert "priya@example.com" not in serialised
    assert "98765" not in serialised


@pytest.mark.asyncio
async def test_endpoint_rejects_a_non_pdf(client):
    token = await _token(client)
    response = await client.post(
        "/job-match",
        headers={"Authorization": f"Bearer {token}"},
        data={"username": "priya", "company": "Acme", "job_description": JD_TEXT},
        files={"resume_pdf": ("cv.txt", b"just text", "text/plain")},
    )
    assert response.status_code == 422
    assert "not a PDF" in response.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_rejects_an_oversized_pdf(client, monkeypatch):
    from app.services import resume_parser as parser_module

    monkeypatch.setattr(parser_module.settings, "resume_max_bytes", 500)
    token = await _token(client)
    response = await client.post(
        "/job-match",
        headers={"Authorization": f"Bearer {token}"},
        data={"username": "priya", "company": "Acme", "job_description": JD_TEXT},
        files={"resume_pdf": ("cv.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_endpoint_reports_an_unknown_github_user(client):
    token = await _token(client)
    response = await client.post(
        "/job-match",
        headers={"Authorization": f"Bearer {token}"},
        data={"username": "ghost", "company": "Acme", "job_description": JD_TEXT},
        files={"resume_pdf": ("cv.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_validates_missing_fields(client):
    token = await _token(client)
    response = await client.post(
        "/job-match",
        headers={"Authorization": f"Bearer {token}"},
        data={"username": "priya", "company": "Acme"},
        files={"resume_pdf": ("cv.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reports_are_stored_and_retrievable(client):
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(
        "/job-match", headers=headers,
        data={"username": "priya", "company": "Acme", "job_description": JD_TEXT},
        files={"resume_pdf": ("cv.pdf", make_pdf(), "application/pdf")},
    )

    listing = await client.get("/job-match/reports", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    summary = listing.json()[0]
    assert summary["company"] == "Acme"

    detail = await client.get(f"/job-match/reports/{summary['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["overall_match"] == summary["overall_match"]

    removed = await client.delete(f"/job-match/reports/{summary['id']}", headers=headers)
    assert removed.status_code == 204
    assert await (await client.get("/job-match/reports", headers=headers)).aread() == b"[]"


@pytest.mark.asyncio
async def test_existing_endpoints_still_work(client):
    """Regression guard: the new feature must not disturb what was already there."""
    assert (await client.get("/health")).status_code == 200

    spec = (await client.get("/openapi.json")).json()["paths"]
    for path in ("/analyze", "/compare", "/developer/{username}", "/score/{username}",
                 "/repo-chat/index", "/repo-chat/sessions", "/job-match"):
        assert path in spec, f"{path} disappeared from the API"
