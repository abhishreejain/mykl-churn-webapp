"""Churn-stage service helpers for the webapp backend."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any

import pandas as pd


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"
RUNTIME_SRC = RUNTIME_ROOT / "src"
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from churn_model.config import ProjectConfig, load_yaml
from churn_model.io import read_scoring_input
from churn_model.schema import canonicalize_scoring_identifier_columns, detect_scoring_scan_columns
from churn_model.scoring import prepare_scoring_input
from churn_model.web_runtime import SCORED_OUTPUT_COLUMNS, ScoringJobRequest, run_scoring_job


ALLOWED_UPLOAD_EXTENSIONS = {".xlsx", ".xls"}
DEFAULT_RUNTIME_CONFIG_PATH = RUNTIME_ROOT / "artifacts" / "production" / "config_used.yaml"
DEFAULT_RUNTIME_METADATA_PATH = RUNTIME_ROOT / "artifacts" / "production" / "metadata.json"
DEFAULT_MODEL_PATH = RUNTIME_ROOT / "artifacts" / "production" / "churn_model.joblib"


class UploadValidationError(ValueError):
    """Raised when uploaded workbook is not valid for scoring."""


class ChurnRunError(RuntimeError):
    """Raised when churn scoring stage fails."""


def validate_scoring_workbook(
    input_path: str | Path,
    *,
    runtime_config_path: str | Path = DEFAULT_RUNTIME_CONFIG_PATH,
    manual_scan_columns: list[str] | None = None,
    state_column: str | None = None,
    name_column: str | None = None,
    mobile_column: str | None = None,
) -> dict[str, Any]:
    """Validate uploaded workbook using the same rules as scoring runtime."""
    workbook_path = Path(input_path)
    extension = workbook_path.suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported file type `{workbook_path.suffix}`. Only .xlsx and .xls are accepted."
        )
    if not workbook_path.exists():
        raise UploadValidationError(f"Input workbook not found: {workbook_path.name}")

    try:
        raw = read_scoring_input(workbook_path)
        cfg = _build_scoring_cfg(Path(runtime_config_path))

        canonical_frame, resolved_identifiers = canonicalize_scoring_identifier_columns(
            raw.copy(),
            state_column=state_column,
            name_column=name_column,
            mobile_column=mobile_column,
        )
        scan_columns = detect_scoring_scan_columns(
            canonical_frame,
            manual_scan_columns=manual_scan_columns,
        )
        prepared = prepare_scoring_input(
            raw.copy(),
            cfg,
            manual_scan_columns=manual_scan_columns,
            state_column=state_column,
            name_column=name_column,
            mobile_column=mobile_column,
        )
    except Exception as exc:
        raise UploadValidationError(str(exc)) from exc

    mobile_series = prepared.get("mobile_id", pd.Series(dtype="string"))
    unusable_mobile_rows = int(mobile_series.isna().sum()) if not mobile_series.empty else 0
    duplicate_mobile_rows = int(
        (mobile_series.notna() & mobile_series.duplicated(keep=False)).sum()
    ) if not mobile_series.empty else 0

    return {
        "ok": True,
        "input_path": workbook_path.name,
        "row_count": int(len(raw)),
        "resolved_identifier_columns": resolved_identifiers,
        "scan_columns": scan_columns,
        "scan_column_count": len(scan_columns),
        "scan_order_policy": "left_to_right_oldest_to_newest",
        "duplicate_mobile_rows_after_policy": duplicate_mobile_rows,
        "unusable_mobile_rows": unusable_mobile_rows,
    }


def run_churn_scoring(
    input_path: str | Path,
    output_path: str | Path,
    *,
    runtime_config_path: str | Path = DEFAULT_RUNTIME_CONFIG_PATH,
    metadata_path: str | Path = DEFAULT_RUNTIME_METADATA_PATH,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    manual_scan_columns: list[str] | None = None,
    state_column: str | None = None,
    name_column: str | None = None,
    mobile_column: str | None = None,
    validate_first: bool = True,
) -> dict[str, Any]:
    """Run churn scoring with original runtime logic."""
    validation_summary: dict[str, Any] | None = None
    if validate_first:
        validation_summary = validate_scoring_workbook(
            input_path=input_path,
            runtime_config_path=runtime_config_path,
            manual_scan_columns=manual_scan_columns,
            state_column=state_column,
            name_column=name_column,
            mobile_column=mobile_column,
        )

    request = ScoringJobRequest(
        input_path=Path(input_path),
        output_path=Path(output_path),
        model_path=Path(model_path),
        runtime_config_path=Path(runtime_config_path),
        metadata_path=Path(metadata_path),
        manual_scan_columns=manual_scan_columns,
        state_column=state_column,
        name_column=name_column,
        mobile_column=mobile_column,
        project_root=RUNTIME_ROOT,
    )
    runtime_result = run_scoring_job(request=request, raise_on_error=False)
    runtime_payload = asdict(runtime_result)

    if not runtime_result.success:
        message = _friendly_runtime_error(runtime_payload.get("errors", []), stage="churn")
        raise ChurnRunError(message)

    output_frame = _read_csv_with_fallback(Path(output_path))
    actual_columns = [str(col) for col in output_frame.columns]
    if actual_columns != SCORED_OUTPUT_COLUMNS:
        raise ChurnRunError(
            "Churn output schema mismatch. "
            f"Expected {SCORED_OUTPUT_COLUMNS}, found {actual_columns}."
        )

    return {
        "ok": True,
        "stage": "churn_scoring",
        "input_path": Path(input_path).name,
        "output_path": Path(output_path).name,
        "input_row_count": int(runtime_result.input_row_count or 0),
        "output_row_count": int(runtime_result.output_row_count or 0),
        "warnings": list(runtime_result.warnings),
        "validation": validation_summary or {},
        "runtime_result": runtime_payload,
    }


def run_pipeline_with_dashboard(
    input_path: str | Path,
    churn_output_path: str | Path,
    final_output_path: str | Path,
    *,
    runtime_config_path: str | Path = DEFAULT_RUNTIME_CONFIG_PATH,
    metadata_path: str | Path = DEFAULT_RUNTIME_METADATA_PATH,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    lookup_path: str | Path | None = None,
    bucket_config_path: str | Path | None = None,
    manual_scan_columns: list[str] | None = None,
    state_column: str | None = None,
    name_column: str | None = None,
    mobile_column: str | None = None,
) -> dict[str, Any]:
    """Run upload -> churn -> potential -> dashboard flow."""
    churn_result = run_churn_scoring(
        input_path=input_path,
        output_path=churn_output_path,
        runtime_config_path=runtime_config_path,
        metadata_path=metadata_path,
        model_path=model_path,
        manual_scan_columns=manual_scan_columns,
        state_column=state_column,
        name_column=name_column,
        mobile_column=mobile_column,
        validate_first=True,
    )

    from .dashboard_service import build_dashboard_dataset
    from .potential_service import run_potential_enrichment

    potential_result = run_potential_enrichment(
        input_path=churn_output_path,
        output_path=final_output_path,
        lookup_path=lookup_path,
    )
    dashboard = build_dashboard_dataset(
        final_output_path=final_output_path,
        bucket_config_path=bucket_config_path,
    )

    return {
        "ok": True,
        "input_path": Path(input_path).name,
        "churn_output_path": Path(churn_output_path).name,
        "final_output_path": Path(final_output_path).name,
        "churn": churn_result,
        "potential": potential_result,
        "dashboard": dashboard,
    }


def _build_scoring_cfg(runtime_config_path: Path) -> ProjectConfig:
    duplicate_policy = "error"
    if runtime_config_path.exists():
        data = load_yaml(runtime_config_path)
        if isinstance(data, dict):
            scoring_cfg = data.get("scoring", {})
            if isinstance(scoring_cfg, dict):
                duplicate_policy = str(scoring_cfg.get("duplicate_mobile_policy", "error")).strip() or "error"
    return ProjectConfig(root=RUNTIME_ROOT, values={"scoring": {"duplicate_mobile_policy": duplicate_policy}})


def _friendly_runtime_error(errors: list[Any], stage: str) -> str:
    if errors:
        message = str(errors[0])
    else:
        message = f"{stage} stage failed with an unknown runtime error."
    return message


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Unable to decode CSV output file: {path.name}")
