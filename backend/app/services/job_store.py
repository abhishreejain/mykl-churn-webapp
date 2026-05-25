"""Job storage helpers for local backend execution."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
JOBS_ROOT = BACKEND_ROOT / "runtime" / "jobs"
ALLOWED_JOB_ID = re.compile(r"^job_[a-z0-9_]{12,}$")


def ensure_job_root() -> Path:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    return JOBS_ROOT


def create_job_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(4)
    return f"job_{timestamp}_{suffix}"


def validate_job_id(job_id: str) -> bool:
    return bool(ALLOWED_JOB_ID.fullmatch(job_id))


def job_dir(job_id: str) -> Path:
    return ensure_job_root() / job_id


def input_dir(job_id: str) -> Path:
    path = job_dir(job_id) / "input"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(job_id: str) -> Path:
    path = job_dir(job_id) / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def metadata_path(job_id: str) -> Path:
    return job_dir(job_id) / "job_meta.json"


def write_metadata(job_id: str, payload: dict[str, Any]) -> None:
    path = metadata_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_metadata(job_id: str) -> dict[str, Any] | None:
    path = metadata_path(job_id)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def list_job_ids() -> list[str]:
    root = ensure_job_root()
    entries = [path.name for path in root.iterdir() if path.is_dir() and validate_job_id(path.name)]
    return sorted(entries)


def processing_lock_path(job_id: str) -> Path:
    return job_dir(job_id) / ".processing.lock"


def try_acquire_processing_lock(job_id: str) -> bool:
    lock_path = processing_lock_path(job_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(datetime.now(timezone.utc).isoformat())
    return True


def release_processing_lock(job_id: str) -> None:
    lock_path = processing_lock_path(job_id)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
