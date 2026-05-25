"""Pipeline execution using original project scripts and runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

from .dashboard_service import build_dashboard_dataset
from .job_store import output_dir, read_metadata, write_metadata


SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _existing_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _resolve_runtime_layout(
    *,
    service_root: Path | None = None,
    env_repo_root: str | None = None,
    search_roots: list[Path] | None = None,
) -> dict[str, Path]:
    """Resolve script/src/artifact paths for local and Render layouts.

    Resolution order:
    1) `MYKL_REPO_ROOT` (or provided env_repo_root) for full original repo layout.
    2) Upward scan from this module for a full original repo layout.
    3) Upward scan for packaged runtime layout containing `runtime/scripts`.
    4) Default to `<service_root>/runtime` packaged layout.
    """
    resolved_service_root = (service_root or SERVICE_ROOT).resolve()
    configured_repo_root = env_repo_root if env_repo_root is not None else os.getenv("MYKL_REPO_ROOT")

    explicit_roots = [Path(configured_repo_root).expanduser().resolve()] if configured_repo_root else []
    inferred_roots = [path.resolve() for path in (search_roots or list(Path(__file__).resolve().parents))]
    candidate_roots: list[Path] = []
    seen: set[str] = set()
    for root in explicit_roots + inferred_roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        candidate_roots.append(root)

    def build_original_layout(candidate_root: Path) -> dict[str, Path] | None:
        scripts_dir = candidate_root / "scripts"
        src_dir = candidate_root / "src"
        artifacts_dir = candidate_root / "artifacts" / "production"
        score_script = scripts_dir / "score_input_file.py"
        potential_script = scripts_dir / "add_potential_to_scored_file.py"
        runtime_config = artifacts_dir / "config_used.yaml"
        runtime_metadata = artifacts_dir / "metadata.json"
        potential_lookup = artifacts_dir / "potential_lookup_2024_2025.parquet"
        frontend_bucket = _existing_path(
            [
                candidate_root / "mykl_churn_webapp" / "frontend" / "ui_bucket_config.json",
                candidate_root / "frontend" / "ui_bucket_config.json",
            ]
        )
        if (
            score_script.exists()
            and potential_script.exists()
            and src_dir.exists()
            and runtime_config.exists()
            and runtime_metadata.exists()
            and potential_lookup.exists()
            and frontend_bucket is not None
        ):
            return {
                "mode": Path("original"),
                "repo_root": candidate_root,
                "scripts_dir": scripts_dir,
                "src_dir": src_dir,
                "artifacts_dir": artifacts_dir,
                "score_script": score_script,
                "potential_script": potential_script,
                "runtime_config": runtime_config,
                "runtime_metadata": runtime_metadata,
                "potential_lookup": potential_lookup,
                "frontend_bucket_config": frontend_bucket,
            }
        return None

    for candidate_root in candidate_roots:
        original_layout = build_original_layout(candidate_root)
        if original_layout:
            return original_layout

    for candidate_root in candidate_roots:
        runtime_root = candidate_root / "runtime"
        runtime_scripts = runtime_root / "scripts"
        runtime_src = runtime_root / "src"
        runtime_artifacts = runtime_root / "artifacts" / "production"
        score_script = runtime_scripts / "score_input_file.py"
        potential_script = runtime_scripts / "add_potential_to_scored_file.py"
        runtime_config = runtime_artifacts / "config_used.yaml"
        runtime_metadata = runtime_artifacts / "metadata.json"
        potential_lookup = runtime_artifacts / "potential_lookup_2024_2025.parquet"
        frontend_bucket = _existing_path(
            [
                candidate_root / "frontend" / "ui_bucket_config.json",
                candidate_root.parent / "frontend" / "ui_bucket_config.json",
                runtime_root / "ui_bucket_config.json",
            ]
        )
        if (
            score_script.exists()
            and potential_script.exists()
            and runtime_src.exists()
            and runtime_config.exists()
            and runtime_metadata.exists()
            and potential_lookup.exists()
            and frontend_bucket is not None
        ):
            return {
                "mode": Path("packaged_runtime"),
                "repo_root": candidate_root,
                "scripts_dir": runtime_scripts,
                "src_dir": runtime_src,
                "artifacts_dir": runtime_artifacts,
                "score_script": score_script,
                "potential_script": potential_script,
                "runtime_config": runtime_config,
                "runtime_metadata": runtime_metadata,
                "potential_lookup": potential_lookup,
                "frontend_bucket_config": frontend_bucket,
            }

    runtime_root = resolved_service_root / "runtime"
    runtime_scripts = runtime_root / "scripts"
    runtime_src = runtime_root / "src"
    runtime_artifacts = runtime_root / "artifacts" / "production"
    score_script = runtime_scripts / "score_input_file.py"
    potential_script = runtime_scripts / "add_potential_to_scored_file.py"
    runtime_config = runtime_artifacts / "config_used.yaml"
    runtime_metadata = runtime_artifacts / "metadata.json"
    potential_lookup = runtime_artifacts / "potential_lookup_2024_2025.parquet"
    frontend_bucket = _existing_path(
        [
            resolved_service_root.parent / "frontend" / "ui_bucket_config.json",
            resolved_service_root / "frontend" / "ui_bucket_config.json",
            runtime_root / "ui_bucket_config.json",
        ]
    )

    required = [
        score_script,
        potential_script,
        runtime_src,
        runtime_config,
        runtime_metadata,
        potential_lookup,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if frontend_bucket is None:
        missing.append(
            f"ui_bucket_config.json (checked: "
            f"{resolved_service_root.parent / 'frontend' / 'ui_bucket_config.json'}, "
            f"{resolved_service_root / 'frontend' / 'ui_bucket_config.json'}, "
            f"{runtime_root / 'ui_bucket_config.json'})"
        )

    if missing:
        raise RuntimeError(
            "Unable to resolve runtime layout for processing. Missing required files: "
            + "; ".join(missing)
            + ". Ensure the deploy contains either full original repo roots (scripts/src/artifacts) "
            + "or packaged backend/runtime with frontend/ui_bucket_config.json."
        )

    return {
        "mode": Path("packaged_runtime_fallback"),
        "repo_root": resolved_service_root,
        "scripts_dir": runtime_scripts,
        "src_dir": runtime_src,
        "artifacts_dir": runtime_artifacts,
        "score_script": score_script,
        "potential_script": potential_script,
        "runtime_config": runtime_config,
        "runtime_metadata": runtime_metadata,
        "potential_lookup": potential_lookup,
        "frontend_bucket_config": frontend_bucket,
    }


RUNTIME_LAYOUT = _resolve_runtime_layout()
REPO_ROOT = Path(RUNTIME_LAYOUT["repo_root"])
ORIGINAL_SCRIPTS_DIR = Path(RUNTIME_LAYOUT["scripts_dir"])
ORIGINAL_SRC_DIR = Path(RUNTIME_LAYOUT["src_dir"])
ORIGINAL_ARTIFACTS_DIR = Path(RUNTIME_LAYOUT["artifacts_dir"])
FRONTEND_BUCKET_CONFIG = Path(RUNTIME_LAYOUT["frontend_bucket_config"])

SCORE_SCRIPT = Path(RUNTIME_LAYOUT["score_script"])
POTENTIAL_SCRIPT = Path(RUNTIME_LAYOUT["potential_script"])
RUNTIME_CONFIG = Path(RUNTIME_LAYOUT["runtime_config"])
RUNTIME_METADATA = Path(RUNTIME_LAYOUT["runtime_metadata"])
POTENTIAL_LOOKUP = Path(RUNTIME_LAYOUT["potential_lookup"])

FINAL_CSV_NAME = "final_enriched_output.csv"
FINAL_XLSX_NAME = "final_enriched_output.xlsx"
CHURN_CSV_NAME = "churn_output.csv"

SCORED_COLUMNS = ["State", "Customer name", "Customer mobile number", "Churn probability", "Risk"]
FINAL_COLUMNS = [
    "State",
    "Customer name",
    "Customer mobile number",
    "Churn probability",
    "Risk",
    "Potential",
    "Potential Band",
]


class UploadValidationError(ValueError):
    """Raised when upload workbook fails validation."""


class StageExecutionError(RuntimeError):
    """Raised when scoring or potential stage fails."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class ProcessArtifacts:
    churn_csv: Path
    final_csv: Path
    final_xlsx: Path


def validate_workbook_for_scoring(input_path: Path) -> dict[str, Any]:
    if input_path.suffix.lower() not in {".xlsx", ".xls"}:
        raise UploadValidationError("Unsupported file type. Only .xlsx or .xls is accepted.")
    if not input_path.exists():
        raise UploadValidationError("Uploaded workbook not found on server.")

    sys.path.insert(0, str(ORIGINAL_SRC_DIR))
    try:
        from churn_model.config import ProjectConfig, load_yaml
        from churn_model.io import read_scoring_input
        from churn_model.schema import canonicalize_scoring_identifier_columns, detect_scoring_scan_columns
        from churn_model.scoring import prepare_scoring_input

        raw = read_scoring_input(input_path)
        runtime_values = load_yaml(RUNTIME_CONFIG) if RUNTIME_CONFIG.exists() else {}
        duplicate_policy = "error"
        if isinstance(runtime_values, dict):
            scoring_cfg = runtime_values.get("scoring", {})
            if isinstance(scoring_cfg, dict):
                duplicate_policy = str(scoring_cfg.get("duplicate_mobile_policy", "error")).strip() or "error"
        cfg = ProjectConfig(root=REPO_ROOT, values={"scoring": {"duplicate_mobile_policy": duplicate_policy}})

        canonical_frame, resolved_identifiers = canonicalize_scoring_identifier_columns(raw.copy())
        scan_columns = detect_scoring_scan_columns(canonical_frame)
        prepared = prepare_scoring_input(raw.copy(), cfg)
        unusable_mobile_rows = int(prepared["mobile_id"].isna().sum()) if "mobile_id" in prepared.columns else 0

        return {
            "ok": True,
            "row_count": int(len(raw)),
            "resolved_identifier_columns": resolved_identifiers,
            "scan_columns": scan_columns,
            "scan_order_policy": "left_to_right_oldest_to_newest",
            "unusable_mobile_rows": unusable_mobile_rows,
        }
    except Exception as exc:
        raise UploadValidationError(str(exc)) from exc
    finally:
        if str(ORIGINAL_SRC_DIR) in sys.path:
            try:
                sys.path.remove(str(ORIGINAL_SRC_DIR))
            except ValueError:
                pass


def run_processing_chain(job_id: str, uploaded_input_path: Path) -> dict[str, Any]:
    if not uploaded_input_path.exists():
        raise StageExecutionError("churn", "Uploaded workbook for the job is missing.")

    out_dir = output_dir(job_id)
    churn_csv = out_dir / CHURN_CSV_NAME
    final_csv = out_dir / FINAL_CSV_NAME
    final_xlsx = out_dir / FINAL_XLSX_NAME

    scoring_command = [
        sys.executable,
        str(SCORE_SCRIPT),
        "--runtime-config",
        str(RUNTIME_CONFIG),
        "--metadata",
        str(RUNTIME_METADATA),
        "--input",
        str(uploaded_input_path),
        "--output",
        str(churn_csv),
    ]
    scoring_result = _run_subprocess(scoring_command, stage="churn")
    _validate_csv_schema(churn_csv, SCORED_COLUMNS, stage="churn")

    potential_command = [
        sys.executable,
        str(POTENTIAL_SCRIPT),
        "--input",
        str(churn_csv),
        "--output",
        str(final_csv),
        "--lookup-output",
        str(POTENTIAL_LOOKUP),
    ]
    potential_result = _run_subprocess(potential_command, stage="potential")
    _validate_csv_schema(final_csv, FINAL_COLUMNS, stage="potential")

    final_df = _read_csv_with_fallback(final_csv)
    final_df.to_excel(final_xlsx, index=False)

    dashboard_payload = build_dashboard_dataset(final_csv, bucket_config_path=FRONTEND_BUCKET_CONFIG)
    dashboard_payload["source_file"] = FINAL_CSV_NAME

    meta = read_metadata(job_id) or {}
    meta.update(
        {
            "job_id": job_id,
            "status": "completed",
            "uploaded_input_filename": uploaded_input_path.name,
            "churn_output_filename": CHURN_CSV_NAME,
            "final_output_filename": FINAL_CSV_NAME,
            "final_output_download_filename": FINAL_XLSX_NAME,
            "counts": {
                "churn_rows": int(len(_read_csv_with_fallback(churn_csv))),
                "final_rows": int(len(final_df)),
            },
            "dashboard_source": FINAL_CSV_NAME,
        }
    )
    write_metadata(job_id, meta)

    return {
        "ok": True,
        "job_id": job_id,
        "status": "completed",
        "counts": {
            "churn_rows": int(len(_read_csv_with_fallback(churn_csv))),
            "final_rows": int(len(final_df)),
        },
        "artifacts": ProcessArtifacts(churn_csv=churn_csv, final_csv=final_csv, final_xlsx=final_xlsx),
        "dashboard": dashboard_payload,
        "stages": {
            "churn": scoring_result,
            "potential": potential_result,
        },
    }


def _run_subprocess(command: list[str], stage: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        raise StageExecutionError(stage, f"Failed to launch {stage} stage.") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        message = stderr or stdout or f"{stage} stage exited with code {proc.returncode}."
        raise StageExecutionError(stage, message)

    return {
        "return_code": int(proc.returncode),
        "status": "ok",
    }


def _validate_csv_schema(path: Path, expected_columns: list[str], stage: str) -> None:
    frame = _read_csv_with_fallback(path)
    actual = [str(col) for col in frame.columns]
    if actual != expected_columns:
        raise StageExecutionError(
            stage,
            f"{stage} output schema mismatch. Expected {expected_columns}, found {actual}",
        )


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Unable to decode CSV file: {path.name}")


def serialize_error(error_type: str, message: str, *, job_id: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "message": message,
        "details": details or {},
    }
    if job_id:
        payload["job_id"] = job_id
    return payload


def persist_stage_failure(job_id: str, *, stage: str, message: str) -> None:
    meta = read_metadata(job_id) or {}
    meta.update(
        {
            "job_id": job_id,
            "status": f"failed_{stage}",
            "failure_stage": stage,
            "failure_message": message,
        }
    )
    write_metadata(job_id, meta)


def load_dashboard_from_final(job_id: str) -> dict[str, Any]:
    meta = read_metadata(job_id)
    if not meta:
        raise FileNotFoundError("Job not found.")
    final_csv = output_dir(job_id) / FINAL_CSV_NAME
    if not final_csv.exists():
        raise FileNotFoundError("Final output is not ready yet.")
    payload = build_dashboard_dataset(final_csv, bucket_config_path=FRONTEND_BUCKET_CONFIG)
    payload["job_id"] = job_id
    payload["source_file"] = FINAL_CSV_NAME
    return payload


def dashboard_with_filters(job_id: str, *, state: str | None, risk: str | None, potential_level: str | None) -> dict[str, Any]:
    meta = read_metadata(job_id)
    if not meta:
        raise FileNotFoundError("Job not found.")
    final_csv = output_dir(job_id) / FINAL_CSV_NAME
    if not final_csv.exists():
        raise FileNotFoundError("Final output is not ready yet.")
    payload = build_dashboard_dataset(
        final_csv,
        bucket_config_path=FRONTEND_BUCKET_CONFIG,
        state=state,
        risk=risk,
        potential_level=potential_level,
    )
    payload["job_id"] = job_id
    payload["source_file"] = FINAL_CSV_NAME
    return payload
