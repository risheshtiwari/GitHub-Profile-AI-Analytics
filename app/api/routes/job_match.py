"""Job-match endpoints.

    POST   /job-match              JD + resume PDF + GitHub username -> full report
    GET    /job-match/reports      your previous reports (summaries)
    GET    /job-match/reports/{id} one stored report in full
    DELETE /job-match/reports/{id} remove a stored report

The uploaded PDF is held in memory for the duration of parsing and never
written to disk. If a caller needs disk-backed processing later, the temp file
must be removed in a `finally` — but not writing it at all is stronger.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import JobMatchReport, User
from app.db.session import get_db
from app.schemas.job_match import JobMatchOut, JobMatchSummaryOut
from app.services import job_match, resume_parser
from app.services.jd_parser import JDError
from app.services.pipeline import DeveloperNotFoundError
from app.services.resume_parser import ResumeError, ResumeTooLargeError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/job-match", tags=["job-match"])

MAX_JD_CHARS = 20_000


@router.post("", response_model=JobMatchOut)
async def create_job_match(
    username: str = Form(..., description="GitHub username of the candidate"),
    company: str = Form(..., description="Hiring company name"),
    job_description: str = Form(..., description="Full text of the job description"),
    resume_pdf: UploadFile = File(..., description="Candidate resume as a PDF"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyse a candidate against a role using three sources of evidence.

    Percentages are computed by a deterministic scoring engine, not by the
    language model. Skills with no public evidence are reported as *unknown*
    rather than as gaps. No demographic or personal characteristic is used.
    """
    username = username.strip()
    company = company.strip()

    if not username:
        raise HTTPException(status_code=400, detail="A GitHub username is required.")
    if not company:
        raise HTTPException(status_code=400, detail="A company name is required.")
    if len(job_description or "") > MAX_JD_CHARS:
        raise HTTPException(status_code=413, detail=f"Job description exceeds {MAX_JD_CHARS} characters.")

    # Read once, into memory, and never persist the bytes.
    try:
        data = await resume_pdf.read()
    finally:
        await resume_pdf.close()

    try:
        resume = await resume_parser.parse_resume_pdf(
            data, content_type=resume_pdf.content_type, filename=resume_pdf.filename
        )
    except ResumeTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except ResumeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        del data  # drop the file bytes as early as possible

    try:
        report = await job_match.run_job_match(
            username=username,
            company=company,
            job_description=job_description,
            resume=resume.to_dict(),
            db=db,
            user_id=current_user.id,
        )
    except JDError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DeveloperNotFoundError:
        raise HTTPException(status_code=404, detail=f"GitHub user '{username}' was not found.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job match failed for %s vs %s", username, company)
        raise HTTPException(status_code=502, detail=f"Analysis failed: {type(exc).__name__}: {exc}")

    return report


@router.get("/reports", response_model=list[JobMatchSummaryOut])
async def list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JobMatchReport)
        .where(JobMatchReport.user_id == current_user.id)
        .order_by(JobMatchReport.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/reports/{report_id}", response_model=JobMatchOut)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await db.get(JobMatchReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if row.user_id is not None and row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="That report belongs to another user.")
    return row.report


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await db.get(JobMatchReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if row.user_id is not None and row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="That report belongs to another user.")
    await db.delete(row)
    await db.commit()
