"""Potential enrichment service helpers for the webapp backend."""

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

from churn_model.potential_enrichment import POTENTIAL_LOOKUP_FILENAME
from churn_model.cleaning import normalize_mobile
from churn_model.web_runtime import FINAL_OUTPUT_COLUMNS, PotentialJobRequest, run_potential_enrichment_job


DEFAULT_LOOKUP_PATH = RUNTIME_ROOT / "artifacts" / "production" / POTENTIAL_LOOKUP_FILENAME


class PotentialRunError(RuntimeError):
    """Raised when potential enrichment fails."""


def run_potential_enrichment(
    input_path: str | Path,
    output_path: str | Path,
    *,
    lookup_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run potential enrichment with the original runtime logic."""
    lookup = Path(lookup_path) if lookup_path else DEFAULT_LOOKUP_PATH
    request = PotentialJobRequest(
        input_path=Path(input_path),
        output_path=Path(output_path),
        lookup_path=lookup,
        project_root=RUNTIME_ROOT,
    )
    runtime_result = run_potential_enrichment_job(request=request, raise_on_error=False)
    runtime_payload = asdict(runtime_result)

    if not runtime_result.success:
        message = _friendly_runtime_error(runtime_payload.get("errors", []))
        raise PotentialRunError(message)

    output_frame = _read_csv_with_fallback(Path(output_path))
    actual_columns = [str(col) for col in output_frame.columns]
    if actual_columns != FINAL_OUTPUT_COLUMNS:
        raise PotentialRunError(
            "Final output schema mismatch after potential enrichment. "
            f"Expected {FINAL_OUTPUT_COLUMNS}, found {actual_columns}."
        )

    cleaned_mobile = output_frame["Customer mobile number"].map(normalize_mobile)
    matched_rows = int(output_frame["Potential"].notna().sum())
    unmatched_rows = int(output_frame["Potential"].isna().sum())
    unusable_mobile_rows = int(cleaned_mobile.isna().sum())

    return {
        "ok": True,
        "stage": "potential_enrichment",
        "input_path": Path(input_path).name,
        "output_path": Path(output_path).name,
        "input_row_count": int(runtime_result.input_row_count or 0),
        "output_row_count": int(runtime_result.output_row_count or 0),
        "matched_rows": matched_rows,
        "unmatched_rows": unmatched_rows,
        "unusable_mobile_rows": unusable_mobile_rows,
        "warnings": list(runtime_result.warnings),
        "runtime_result": runtime_payload,
    }


def _friendly_runtime_error(errors: list[Any]) -> str:
    if errors:
        return str(errors[0])
    return "Potential enrichment failed with an unknown runtime error."


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Unable to decode CSV output file: {path.name}")
