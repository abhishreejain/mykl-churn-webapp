"""Download route for final enriched output."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.services.job_store import output_dir, read_metadata, validate_job_id
from app.services.runtime_pipeline import FINAL_XLSX_NAME, serialize_error


router = APIRouter(tags=["download"])


@router.get("/download/{job_id}/final")
async def download_final(job_id: str):
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
            "Final output is not ready yet. Run processing first.",
            job_id=job_id,
            details={"status": status},
        )
        return JSONResponse(status_code=409, content=payload)

    final_path = output_dir(job_id) / FINAL_XLSX_NAME
    if not final_path.exists():
        payload = serialize_error("NOT_FOUND", "Final output file not found.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)

    return FileResponse(
        path=str(final_path),
        filename=f"{job_id}_final_output.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

