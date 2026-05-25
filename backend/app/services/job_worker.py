"""Background job queue and worker loop for churn/potential processing."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

from .job_store import (
    input_dir,
    list_job_ids,
    read_metadata,
    release_processing_lock,
    try_acquire_processing_lock,
    validate_job_id,
    write_metadata,
)
from .runtime_pipeline import (
    StageExecutionError,
    persist_stage_failure,
    run_processing_chain,
    serialize_error,
)


LOGGER = logging.getLogger("mykl.job_worker")
TERMINAL_STATES = {"completed", "failed_churn", "failed_potential", "failed_internal"}
PROCESSING_STATES = {"processing_churn", "processing_potential"}
QUEUEABLE_STATES = {"uploaded", "failed_churn", "failed_potential", "failed_internal"}


def enqueue_job(job_id: str) -> dict[str, Any]:
    if not validate_job_id(job_id):
        raise ValueError("Invalid job ID format.")
    meta = read_metadata(job_id)
    if not meta:
        raise FileNotFoundError("Job not found.")

    status = str(meta.get("status") or "")
    if status in PROCESSING_STATES:
        return {"ok": True, "job_id": job_id, "status": status, "message": "Job is already processing."}
    if status == "queued":
        return {"ok": True, "job_id": job_id, "status": "queued", "message": "Job is already queued."}
    if status == "completed":
        return {"ok": True, "job_id": job_id, "status": "completed", "message": "Job is already completed."}
    if status not in QUEUEABLE_STATES:
        raise ValueError(f"Job cannot be queued from status `{status}`.")

    now = datetime.now(timezone.utc).isoformat()
    meta.update(
        {
            "status": "queued",
            "queued_at_utc": now,
            "failure_stage": None,
            "failure_message": None,
            "processing_started_at_utc": None,
            "processing_completed_at_utc": None,
        }
    )
    write_metadata(job_id, meta)
    LOGGER.info("job_queued job_id=%s status=%s", job_id, meta.get("status"))
    return {"ok": True, "job_id": job_id, "status": "queued", "message": "Job queued for background processing."}


def get_job_status(job_id: str) -> dict[str, Any]:
    if not validate_job_id(job_id):
        return serialize_error("NOT_FOUND", "Invalid job ID format.", job_id=job_id)
    meta = read_metadata(job_id)
    if not meta:
        return serialize_error("NOT_FOUND", "Job not found.", job_id=job_id)
    return {
        "ok": True,
        "job_id": job_id,
        "status": str(meta.get("status") or "unknown"),
        "message": _status_message(meta),
        "failure_stage": meta.get("failure_stage"),
        "failure_message": meta.get("failure_message"),
        "counts": meta.get("counts", {}),
        "artifacts": {
            "churn_output": meta.get("churn_output_filename"),
            "final_output": meta.get("final_output_filename"),
            "final_download_output": meta.get("final_output_download_filename"),
        },
        "timestamps": {
            "uploaded_at_utc": meta.get("uploaded_at_utc"),
            "queued_at_utc": meta.get("queued_at_utc"),
            "processing_started_at_utc": meta.get("processing_started_at_utc"),
            "processing_completed_at_utc": meta.get("processing_completed_at_utc"),
        },
    }


def process_next_queued_job() -> bool:
    queued = _find_next_queued_job_id()
    if not queued:
        return False
    job_id = queued
    if not try_acquire_processing_lock(job_id):
        return False
    try:
        _process_claimed_job(job_id)
    finally:
        release_processing_lock(job_id)
    return True


def run_worker_loop(*, poll_seconds: float = 2.0, stop_event: threading.Event | None = None) -> None:
    LOGGER.info("worker_loop_started poll_seconds=%s", poll_seconds)
    while True:
        if stop_event and stop_event.is_set():
            LOGGER.info("worker_loop_stopping")
            return
        processed = False
        try:
            processed = process_next_queued_job()
        except Exception as exc:
            LOGGER.exception("worker_loop_iteration_error error=%s", exc)
        if not processed:
            time.sleep(poll_seconds)


def start_embedded_worker_thread(*, poll_seconds: float | None = None) -> threading.Thread:
    interval = poll_seconds if poll_seconds is not None else float(os.getenv("MYKL_JOB_POLL_SECONDS", "2.0"))
    thread = threading.Thread(
        target=run_worker_loop,
        kwargs={"poll_seconds": interval},
        name="mykl-embedded-worker",
        daemon=True,
    )
    thread.start()
    return thread


def _find_next_queued_job_id() -> str | None:
    candidates: list[tuple[str, str]] = []
    for job_id in list_job_ids():
        meta = read_metadata(job_id)
        if not meta:
            continue
        if str(meta.get("status") or "") != "queued":
            continue
        queued_at = str(meta.get("queued_at_utc") or meta.get("uploaded_at_utc") or "")
        candidates.append((queued_at, job_id))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _process_claimed_job(job_id: str) -> None:
    meta = read_metadata(job_id) or {}
    stored_input_filename = str(meta.get("stored_input_filename") or "").strip()
    if not stored_input_filename:
        persist_stage_failure(job_id, stage="internal", message="Uploaded workbook not found for job.")
        LOGGER.error("job_failed_missing_input job_id=%s", job_id)
        return
    uploaded_input_path = input_dir(job_id) / stored_input_filename
    if not uploaded_input_path.exists():
        persist_stage_failure(job_id, stage="internal", message="Uploaded workbook file is missing.")
        LOGGER.error("job_failed_missing_input_file job_id=%s path=%s", job_id, uploaded_input_path)
        return

    now = datetime.now(timezone.utc).isoformat()
    meta.update({"status": "processing_churn", "processing_started_at_utc": now})
    write_metadata(job_id, meta)
    LOGGER.info("job_processing_started job_id=%s input=%s", job_id, uploaded_input_path.name)

    try:
        run_processing_chain(job_id, uploaded_input_path)
    except StageExecutionError as exc:
        persist_stage_failure(job_id, stage=exc.stage, message=str(exc))
        LOGGER.error("job_stage_failed job_id=%s stage=%s error=%s", job_id, exc.stage, exc)
    except Exception as exc:
        persist_stage_failure(job_id, stage="internal", message=str(exc))
        LOGGER.exception("job_internal_failure job_id=%s error=%s", job_id, exc)
    else:
        completed_meta = read_metadata(job_id) or {}
        completed_meta["processing_completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_metadata(job_id, completed_meta)
        LOGGER.info("job_completed job_id=%s", job_id)


def _status_message(meta: dict[str, Any]) -> str:
    status = str(meta.get("status") or "")
    if status == "uploaded":
        return "Upload accepted. Job is waiting to be queued."
    if status == "queued":
        return "Job queued. Waiting for worker."
    if status == "processing_churn":
        return "Running churn scoring stage."
    if status == "processing_potential":
        return "Running potential enrichment stage."
    if status == "completed":
        return "Processing completed successfully."
    if status.startswith("failed"):
        failure_message = str(meta.get("failure_message") or "Processing failed.")
        return failure_message
    return "Job status available."
