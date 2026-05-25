"""Programmatic runtime entry points for web/backend orchestration.

This module wraps the original CLI runtime behavior so the same logic can be
used from:
1) command-line scripts
2) importable backend calls
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

import pandas as pd

from churn_model.config import ProjectConfig, load_yaml
from churn_model.io import read_scoring_input
from churn_model.potential_enrichment import POTENTIAL_LOOKUP_FILENAME, add_potential_to_scored_file
from churn_model.scoring import score_file


SCORED_OUTPUT_COLUMNS = [
    "State",
    "Customer name",
    "Customer mobile number",
    "Churn probability",
    "Risk",
]
FINAL_OUTPUT_COLUMNS = [
    "State",
    "Customer name",
    "Customer mobile number",
    "Churn probability",
    "Risk",
    "Potential",
    "Potential Band",
]


@dataclass(frozen=True)
class ScoringJobRequest:
    input_path: Path
    output_path: Path | None = None
    model_path: Path | None = None
    runtime_config_path: Path = Path("artifacts/production/config_used.yaml")
    metadata_path: Path = Path("artifacts/production/metadata.json")
    manual_scan_columns: list[str] | None = None
    state_column: str | None = None
    name_column: str | None = None
    mobile_column: str | None = None
    project_root: Path = Path(".").resolve()


@dataclass(frozen=True)
class PotentialJobRequest:
    input_path: Path
    output_path: Path
    lookup_path: Path | None = None
    project_root: Path = Path(".").resolve()


@dataclass
class RuntimeJobResult:
    stage: str
    success: bool
    input_path: str
    output_path: str | None
    input_row_count: int | None
    output_row_count: int | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    validation_summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_scoring_job(request: ScoringJobRequest, raise_on_error: bool = False) -> RuntimeJobResult:
    input_path = Path(request.input_path)
    output_path = request.output_path or input_path.with_name(f"{input_path.stem}_scored.csv")
    warnings: list[str] = []
    errors: list[str] = []

    try:
        runtime_values = _resolve_from_runtime_config(Path(request.runtime_config_path))
        cfg = _resolve_scoring_cfg(runtime_values, request.project_root)
        model_path = _resolve_default_model_path(request.model_path, runtime_values, Path(request.metadata_path))

        raw = read_scoring_input(input_path)
        input_row_count = int(len(raw))

        score_file(
            input_path=input_path,
            model_path=model_path,
            output_path=output_path,
            cfg=cfg,
            manual_scan_columns=request.manual_scan_columns,
            state_column=request.state_column,
            name_column=request.name_column,
            mobile_column=request.mobile_column,
        )
        scored = _read_csv_with_fallback(output_path)
        output_row_count = int(len(scored))

        validation_summary = {
            "output_schema_expected": SCORED_OUTPUT_COLUMNS,
            "output_schema_actual": [str(col) for col in scored.columns],
            "output_schema_exact_match": [str(col) for col in scored.columns] == SCORED_OUTPUT_COLUMNS,
            "risk_counts": scored["Risk"].astype("string").fillna("BLANK").value_counts(dropna=False).to_dict(),
            "churn_probability_missing_or_nonnumeric": int(
                pd.to_numeric(scored["Churn probability"], errors="coerce").isna().sum()
            ),
        }
        if output_row_count != input_row_count:
            warnings.append(
                "Output row count differs from input row count. "
                f"input={input_row_count}, output={output_row_count}"
            )

        return RuntimeJobResult(
            stage="scoring",
            success=True,
            input_path=str(input_path),
            output_path=str(output_path),
            input_row_count=input_row_count,
            output_row_count=output_row_count,
            warnings=warnings,
            errors=errors,
            validation_summary=validation_summary,
        )
    except Exception as exc:
        errors.append(str(exc))
        result = RuntimeJobResult(
            stage="scoring",
            success=False,
            input_path=str(input_path),
            output_path=str(output_path),
            input_row_count=None,
            output_row_count=None,
            warnings=warnings,
            errors=errors,
            validation_summary={},
        )
        if raise_on_error:
            raise
        return result


def run_potential_enrichment_job(request: PotentialJobRequest, raise_on_error: bool = False) -> RuntimeJobResult:
    input_path = Path(request.input_path)
    output_path = Path(request.output_path)
    lookup_path = request.lookup_path or Path("artifacts/production") / POTENTIAL_LOOKUP_FILENAME
    warnings: list[str] = []
    errors: list[str] = []

    try:
        scored = _read_csv_with_fallback(input_path)
        input_row_count = int(len(scored))

        add_potential_to_scored_file(
            scored_input_path=input_path,
            scored_output_path=output_path,
            cfg=None,
            lookup_path=lookup_path,
            allow_lookup_build=False,
        )
        final = _read_csv_with_fallback(output_path)
        output_row_count = int(len(final))
        blank_potential_rows = int(final["Potential"].isna().sum())

        if output_row_count != input_row_count:
            warnings.append(
                "Output row count differs from input row count. "
                f"input={input_row_count}, output={output_row_count}"
            )
        if blank_potential_rows > 0:
            warnings.append(
                f"Rows with blank Potential after enrichment: {blank_potential_rows} "
                "(unusable or unmatched mobile IDs)."
            )

        validation_summary = {
            "input_schema_expected": SCORED_OUTPUT_COLUMNS,
            "input_schema_actual": [str(col) for col in scored.columns],
            "input_schema_exact_match": [str(col) for col in scored.columns] == SCORED_OUTPUT_COLUMNS,
            "output_schema_expected": FINAL_OUTPUT_COLUMNS,
            "output_schema_actual": [str(col) for col in final.columns],
            "output_schema_exact_match": [str(col) for col in final.columns] == FINAL_OUTPUT_COLUMNS,
            "potential_band_counts": final["Potential Band"].astype("string").fillna("BLANK").value_counts(dropna=False).to_dict(),
            "blank_potential_rows": blank_potential_rows,
        }

        return RuntimeJobResult(
            stage="potential_enrichment",
            success=True,
            input_path=str(input_path),
            output_path=str(output_path),
            input_row_count=input_row_count,
            output_row_count=output_row_count,
            warnings=warnings,
            errors=errors,
            validation_summary=validation_summary,
        )
    except Exception as exc:
        errors.append(str(exc))
        result = RuntimeJobResult(
            stage="potential_enrichment",
            success=False,
            input_path=str(input_path),
            output_path=str(output_path),
            input_row_count=None,
            output_row_count=None,
            warnings=warnings,
            errors=errors,
            validation_summary={},
        )
        if raise_on_error:
            raise
        return result


def _resolve_scoring_cfg(runtime_values: dict[str, object], project_root: Path) -> ProjectConfig:
    duplicate_policy = "error"
    scoring_cfg = runtime_values.get("scoring", {})
    if isinstance(scoring_cfg, dict):
        duplicate_policy = str(scoring_cfg.get("duplicate_mobile_policy", "error")).strip() or "error"
    return ProjectConfig(root=project_root.resolve(), values={"scoring": {"duplicate_mobile_policy": duplicate_policy}})


def _resolve_from_runtime_config(runtime_config_path: Path) -> dict[str, object]:
    if not runtime_config_path.exists():
        return {}
    data = load_yaml(runtime_config_path)
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_default_model_path(
    model_path: Path | None,
    runtime_values: dict[str, object],
    metadata_path: Path,
) -> Path:
    if model_path:
        return Path(model_path)

    runtime_paths = runtime_values.get("paths", {})
    if isinstance(runtime_paths, dict):
        configured = runtime_paths.get("production_model")
        if configured:
            candidate = Path(str(configured))
            if candidate.exists():
                return candidate

    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
        if isinstance(metadata, dict):
            bundle = metadata.get("production_bundle", {})
            if isinstance(bundle, dict):
                for key in ("legacy_production_model_path", "model_joblib"):
                    raw = bundle.get(key)
                    if not raw:
                        continue
                    candidate = Path(str(raw))
                    if candidate.exists():
                        return candidate

    fallback = Path("artifacts/production/churn_model.joblib")
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        "Could not resolve production model artifact. Provide explicit model path or package "
        "`artifacts/production/churn_model.joblib`."
    )


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Unable to decode CSV input file: {path}")

