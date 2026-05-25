"""Upload route for workbook intake."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.services.job_store import create_job_id, input_dir, validate_job_id, write_metadata
from app.services.runtime_pipeline import UploadValidationError, serialize_error, validate_workbook_for_scoring


router = APIRouter(tags=["upload"])


@router.post("/upload")
async def upload_workbook(file: UploadFile = File(...)) -> JSONResponse:
    original_filename = file.filename or "uploaded_workbook"
    suffix = Path(original_filename).suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        payload = serialize_error(
            "UPLOAD_VALIDATION_FAILURE",
            "Unsupported file type. Please upload .xlsx or .xls workbook.",
            details={"filename": original_filename},
        )
        return JSONResponse(status_code=400, content=payload)

    job_id = create_job_id()
    if not validate_job_id(job_id):
        payload = serialize_error("INTERNAL_ERROR", "Failed to create a valid job ID.")
        return JSONResponse(status_code=500, content=payload)

    job_input_dir = input_dir(job_id)
    saved_name = f"source_workbook{suffix}"
    saved_path = job_input_dir / saved_name
    data = await file.read()
    saved_path.write_bytes(data)

    try:
        validation = validate_workbook_for_scoring(saved_path)
    except UploadValidationError as exc:
        payload = serialize_error(
            "UPLOAD_VALIDATION_FAILURE",
            str(exc),
            job_id=job_id,
            details={"filename": original_filename},
        )
        return JSONResponse(status_code=400, content=payload)
    except Exception:
        payload = serialize_error(
            "INTERNAL_ERROR",
            "Unexpected error while validating workbook.",
            job_id=job_id,
            details={"filename": original_filename},
        )
        return JSONResponse(status_code=500, content=payload)

    write_metadata(
        job_id,
        {
            "job_id": job_id,
            "status": "uploaded",
            "uploaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "original_filename": original_filename,
            "stored_input_filename": saved_name,
            "validation": validation,
        },
    )

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "job_id": job_id,
            "filename": original_filename,
            "message": "Upload accepted.",
            "validation": validation,
        },
    )

