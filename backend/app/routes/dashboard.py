"""Dashboard data route backed by final enriched output."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.job_store import read_metadata, validate_job_id
from app.services.runtime_pipeline import dashboard_with_filters, serialize_error


router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/{job_id}")
async def get_dashboard(
    job_id: str,
    state: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    potential_level: str | None = Query(default=None),
) -> JSONResponse:
    if not validate_job_id(job_id):
        payload = serialize_error("NOT_FOUND", "Invalid job ID format.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)

    meta = read_metadata(job_id)
    if not meta:
        payload = serialize_error("NOT_FOUND", "Job not found.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)
    status = str(meta.get("status") or "")
    if status != "completed":
        payload = serialize_error(
            "DASHBOARD_NOT_READY",
            "Dashboard is not ready yet. Run processing first.",
            job_id=job_id,
            details={"status": status},
        )
        return JSONResponse(status_code=409, content=payload)

    try:
        dashboard = dashboard_with_filters(
            job_id,
            state=state,
            risk=risk,
            potential_level=potential_level,
        )
    except FileNotFoundError:
        payload = serialize_error("DASHBOARD_NOT_READY", "Final enriched output is not available yet.", job_id=job_id)
        return JSONResponse(status_code=409, content=payload)
    except Exception:
        payload = serialize_error("INTERNAL_ERROR", "Failed to build dashboard payload.", job_id=job_id)
        return JSONResponse(status_code=500, content=payload)

    dashboard["ok"] = True
    dashboard["job_id"] = job_id
    return JSONResponse(status_code=200, content=dashboard)

