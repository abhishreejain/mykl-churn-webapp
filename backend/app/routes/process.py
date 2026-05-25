"""Processing route for churn -> potential chain."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.job_store import input_dir, read_metadata, validate_job_id, write_metadata
from app.services.runtime_pipeline import (
    StageExecutionError,
    persist_stage_failure,
    run_processing_chain,
    serialize_error,
)


router = APIRouter(tags=["process"])


@router.post("/process/{job_id}")
async def process_job(job_id: str) -> JSONResponse:
    if not validate_job_id(job_id):
        payload = serialize_error("NOT_FOUND", "Invalid job ID format.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)

    meta = read_metadata(job_id)
    if not meta:
        payload = serialize_error("NOT_FOUND", "Job not found.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)

    stored_input_filename = str(meta.get("stored_input_filename") or "").strip()
    if not stored_input_filename:
        payload = serialize_error("NOT_FOUND", "Uploaded workbook not found for the job.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)
    uploaded_input_path = input_dir(job_id) / stored_input_filename
    if not uploaded_input_path.exists():
        payload = serialize_error("NOT_FOUND", "Uploaded workbook file is missing.", job_id=job_id)
        return JSONResponse(status_code=404, content=payload)

    meta.update(
        {
            "status": "processing_churn",
            "processing_started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_metadata(job_id, meta)

    try:
        result = run_processing_chain(job_id, uploaded_input_path)
    except StageExecutionError as exc:
        error_type = "CHURN_RUN_FAILURE" if exc.stage == "churn" else "POTENTIAL_RUN_FAILURE"
        persist_stage_failure(job_id, stage=exc.stage, message=str(exc))
        payload = serialize_error(error_type, str(exc), job_id=job_id)
        return JSONResponse(status_code=400, content=payload)
    except Exception as exc:
        persist_stage_failure(job_id, stage="internal", message=str(exc))
        payload = serialize_error("INTERNAL_ERROR", "Unexpected processing failure.", job_id=job_id)
        return JSONResponse(status_code=500, content=payload)

    churn_artifact = result["artifacts"].churn_csv
    final_artifact = result["artifacts"].final_csv
    final_download_artifact = result["artifacts"].final_xlsx
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "job_id": job_id,
            "status": "completed",
            "message": "Processing completed successfully.",
            "counts": result["counts"],
            "stages": result["stages"],
            "artifacts": {
                "churn_output": churn_artifact.name,
                "final_output": final_artifact.name,
                "final_download_output": final_download_artifact.name,
            },
        },
    )

