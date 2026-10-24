from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from .candidate_presenter import candidate_out
from ..common import loads
from ..jobs.manager import JobManager
from ..persistence.repositories import Repository, row_to_dict
from ..reporting.export import candidates_to_csv, job_report
from ..schemas.jobs import (
    CandidateListResponse,
    CandidateOut,
    CreateJobRequest,
    CreateJobResponse,
    JobListResponse,
    JobSummary,
    JobParams,
    JobTrackListResponse,
    JobTrackOut,
)
from .deps import get_manager, get_repo, require_token

router = APIRouter(prefix="/api/v1", tags=["jobs"], dependencies=[Depends(require_token)])


def _candidate_out(row) -> CandidateOut:
    return candidate_out(row)


def _report_candidate(row) -> dict:
    data = dict(row)
    view = candidate_out(row)
    data.pop("beat_times_json", None)
    data.update(time_ms=view.time_ms, beat=view.beat, original_time_ms=view.original_time_ms)
    return data


@router.post("/jobs", response_model=CreateJobResponse, status_code=201)
def create_job(req: CreateJobRequest, manager: JobManager = Depends(get_manager)) -> CreateJobResponse:
    job_id = manager.submit(
        params=req.params.model_dump(),
        tracks=[t.model_dump() for t in req.tracks],
    )
    return CreateJobResponse(job_id=job_id)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(repo: Repository = Depends(get_repo)) -> JobListResponse:
    return JobListResponse(jobs=[_job_summary(r) for r in repo.list_jobs()])


@router.get("/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str, repo: Repository = Depends(get_repo)) -> JobSummary:
    row = repo.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_summary(row)


def _job_summary(row) -> JobSummary:
    return JobSummary(**dict(row), params=JobParams(**(loads(row["params_json"]) or {})))


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, manager: JobManager = Depends(get_manager)) -> dict[str, bool]:
    return {"cancelled": manager.cancel(job_id)}


@router.get("/jobs/{job_id}/tracks", response_model=JobTrackListResponse)
def job_tracks(job_id: str, repo: Repository = Depends(get_repo)) -> JobTrackListResponse:
    if repo.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    out: list[JobTrackOut] = []
    for jt in repo.list_job_tracks(job_id):
        tr = repo.get_track(jt["track_id"])
        if tr is None:
            continue
        out.append(
            JobTrackOut(
                id=tr["id"],
                content_id=tr["content_id"],
                path=tr["path"],
                format=tr["format"],
                duration_ms=tr["duration_ms"],
                status=jt["status"],
                analysis=loads(jt["analysis_json"]),
            )
        )
    return JobTrackListResponse(tracks=out)


@router.get("/jobs/{job_id}/candidates", response_model=CandidateListResponse)
def job_candidates(job_id: str, repo: Repository = Depends(get_repo)) -> CandidateListResponse:
    if repo.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    rows = repo.list_candidates_for_job(job_id)
    return CandidateListResponse(candidates=[_candidate_out(r) for r in rows])


@router.get("/jobs/{job_id}/report")
def job_report_json(job_id: str, repo: Repository = Depends(get_repo)) -> dict:
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    cands = [_report_candidate(r) for r in repo.list_candidates_for_job(job_id)]
    return job_report(row_to_dict(job), cands)


@router.get("/jobs/{job_id}/export.csv", response_class=PlainTextResponse)
def job_export_csv(job_id: str, repo: Repository = Depends(get_repo)) -> str:
    if repo.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    rows = [_report_candidate(r) for r in repo.list_candidates_for_job(job_id)]
    return candidates_to_csv(rows)
