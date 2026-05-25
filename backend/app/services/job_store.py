"""Job storage helpers for local backend execution."""

from __future__ import annotations

from datetime import datetime, timezone
import json
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

