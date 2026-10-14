"""Dashboard REST API (/api/...). Every endpoint returns quickly; the slow work happens in the worker."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import repository as repo
from .database import open_db

router = APIRouter(prefix="/api", tags=["dashboard"])


def _db(request: Request):
    return open_db(request.app.state.settings.database_path)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/pulls", status_code=202)
def start_pull(request: Request):
    """Queue a trade pull and return immediately (202 Accepted) with the job id.

    The worker process does the actual 15-minute download. If a pull is already
    queued or running, no new job is created and 409 Conflict is returned with that job.
    """
    with _db(request) as conn:
        job, created = repo.create_pull_job(conn)
    if not created:
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"A pull is already {job['status']} (job #{job['id']}).",
                "job_id": job["id"],
                "status": job["status"],
                "job": job,
            },
        )
    return {"job_id": job["id"], "status": job["status"], "job": job}


@router.get("/pulls/latest")
def latest_pull(request: Request) -> dict:
    with _db(request) as conn:
        return {
            "job": repo.get_latest_job(conn),
            "last_successful_pull_at": repo.last_successful_pull_at(conn),
        }


@router.get("/pulls/{job_id}")
def pull_status(job_id: int, request: Request) -> dict:
    with _db(request) as conn:
        job = repo.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Pull job {job_id} not found")
    return job


@router.get("/trades")
def list_trades(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=repo.MAX_PAGE_SIZE),
    search: str = Query("", max_length=100),
) -> dict:
    with _db(request) as conn:
        return repo.list_trades(conn, page, page_size, search)


@router.get("/stats")
def stats(request: Request) -> dict:
    with _db(request) as conn:
        return {**repo.get_stats(conn), "last_successful_pull_at": repo.last_successful_pull_at(conn)}


@router.get("/dashboard")
def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=repo.MAX_PAGE_SIZE),
    search: str = Query("", max_length=100),
) -> dict:
    with _db(request) as conn:
        return repo.dashboard_snapshot(conn, page, page_size, search)
