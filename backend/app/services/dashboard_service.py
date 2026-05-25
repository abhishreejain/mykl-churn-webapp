"""Dashboard aggregation service for MYKL churn webapp."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"
RUNTIME_SRC = RUNTIME_ROOT / "src"
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from churn_model.web_runtime import FINAL_OUTPUT_COLUMNS


DEFAULT_BUCKET_CONFIG_PATH = Path(__file__).resolve().parents[3] / "frontend" / "ui_bucket_config.json"
ALLOWED_PRIORITY_BUCKETS = ("RED", "ORANGE", "GREEN", "OTHER")
SUPPORTED_RISK_VALUES = ("HIGH RISK", "MEDIUM RISK", "LOW RISK")


class DashboardBuildError(RuntimeError):
    """Raised when dashboard dataset cannot be built."""


def build_dashboard_dataset(
    final_output_path: str | Path,
    *,
    bucket_config_path: str | Path | None = None,
    state: str | None = None,
    risk: str | None = None,
    potential_level: str | None = None,
) -> dict[str, Any]:
    """Build dashboard-ready aggregates and filterable records from final output."""
    output_path = Path(final_output_path)
    if not output_path.exists():
        raise DashboardBuildError(f"Final output file not found: {output_path.name}")

    final_df = _read_csv_with_fallback(output_path)
    actual_columns = [str(col) for col in final_df.columns]
    if actual_columns != FINAL_OUTPUT_COLUMNS:
        raise DashboardBuildError(
            "Final output schema mismatch for dashboard aggregation. "
            f"Expected {FINAL_OUTPUT_COLUMNS}, found {actual_columns}."
        )

    config = _load_bucket_config(Path(bucket_config_path) if bucket_config_path else DEFAULT_BUCKET_CONFIG_PATH)
    work = final_df.copy()
    work["__row_order"] = range(len(work))
    work["State"] = work["State"].astype("string").fillna("").str.strip()
    work["Risk"] = work["Risk"].astype("string").fillna("UNKNOWN").str.strip().str.upper()
    work["Potential Band"] = work["Potential Band"].astype("string").fillna("BLANK").str.strip()

    potential_mapping = config["potential_band_to_level"]
    risk_level_bucket_mapping = config["risk_potential_level_to_priority_bucket"]

    potential_level_warnings: list[str] = []
    work["Potential Level"] = work["Potential Band"].map(lambda x: _map_potential_level(x, potential_mapping, potential_level_warnings))

    priority_warnings: list[str] = []
    work["Priority Bucket"] = work.apply(
        lambda row: _map_priority_bucket(
            risk=str(row["Risk"]),
            potential_level=str(row["Potential Level"]),
            mapping=risk_level_bucket_mapping,
            warnings=priority_warnings,
        ),
        axis=1,
    )

    all_records = _build_influencer_records(work)
    filtered_records = _apply_record_filters(all_records, state=state, risk=risk, potential_level=potential_level)

    return {
        "ok": True,
        "input_path": output_path.name,
        "row_count": int(len(work)),
        "state_list": _sorted_unique(work["State"], exclude_blank=True),
        "risk_list": _build_risk_list(work["Risk"]),
        "potential_level_list": _build_potential_level_list(work["Potential Level"]),
        "priority_bucket_counts": _value_counts_dict(work["Priority Bucket"], preferred_order=list(ALLOWED_PRIORITY_BUCKETS)),
        "counts_by_state": _value_counts_dict(work["State"], exclude_blank=True),
        "counts_by_risk": _value_counts_dict(work["Risk"], preferred_order=list(SUPPORTED_RISK_VALUES)),
        "counts_by_potential_level": _value_counts_dict(work["Potential Level"], preferred_order=["HIGH", "MEDIUM", "LOW", "OTHER"]),
        "influencer_records": filtered_records,
        "all_influencer_records_count": len(all_records),
        "filtered_record_count": len(filtered_records),
        "applied_filters": {
            "state": state,
            "risk": risk,
            "potential_level": potential_level,
        },
        "warnings": sorted(set(potential_level_warnings + priority_warnings)),
    }


def _load_bucket_config(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise DashboardBuildError(f"Bucket config file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DashboardBuildError(f"Invalid JSON in bucket config: {path.name}") from exc

    potential_map_raw = payload.get("potential_band_to_level")
    risk_level_map_raw = payload.get("risk_potential_level_to_priority_bucket")
    if not isinstance(potential_map_raw, dict) or not isinstance(risk_level_map_raw, dict):
        raise DashboardBuildError(
            "Bucket config must define `potential_band_to_level` and "
            "`risk_potential_level_to_priority_bucket` as mapping objects."
        )

    potential_band_to_level = {
        str(band).strip(): str(level).strip().upper()
        for band, level in potential_map_raw.items()
    }
    risk_potential_level_to_priority_bucket = {
        str(key).strip().upper(): str(value).strip().upper()
        for key, value in risk_level_map_raw.items()
    }
    return {
        "potential_band_to_level": potential_band_to_level,
        "risk_potential_level_to_priority_bucket": risk_potential_level_to_priority_bucket,
    }


def _map_potential_level(
    potential_band: str,
    mapping: dict[str, str],
    warnings: list[str],
) -> str:
    band = potential_band if potential_band else "BLANK"
    if band in mapping:
        return mapping[band]

    warning = f"Unmapped Potential Band `{band}` routed to OTHER."
    warnings.append(warning)
    return "OTHER"


def _map_priority_bucket(
    *,
    risk: str,
    potential_level: str,
    mapping: dict[str, str],
    warnings: list[str],
) -> str:
    combo = f"{risk}|{potential_level}".upper()
    mapped = mapping.get(combo)
    if mapped is None:
        warnings.append(f"Unmapped Risk x Potential Level `{combo}` routed to OTHER.")
        return "OTHER"
    if mapped not in ALLOWED_PRIORITY_BUCKETS:
        warnings.append(f"Unsupported priority bucket `{mapped}` for `{combo}` routed to OTHER.")
        return "OTHER"
    return mapped


def _build_influencer_records(work: pd.DataFrame) -> list[dict[str, Any]]:
    sorted_work = work.sort_values("__row_order", kind="stable")
    records: list[dict[str, Any]] = []
    for _, row in sorted_work.iterrows():
        records.append(
            {
                "state": str(row["State"]),
                "customer_name": str(row["Customer name"]) if not pd.isna(row["Customer name"]) else "",
                "customer_mobile_number": str(row["Customer mobile number"]) if not pd.isna(row["Customer mobile number"]) else "",
                "churn_probability": _safe_number(row["Churn probability"]),
                "risk": str(row["Risk"]),
                "potential": _safe_number(row["Potential"]),
                "potential_band": str(row["Potential Band"]),
                "potential_level": str(row["Potential Level"]),
                "priority_bucket": str(row["Priority Bucket"]),
            }
        )
    return records


def _apply_record_filters(
    records: list[dict[str, Any]],
    *,
    state: str | None,
    risk: str | None,
    potential_level: str | None,
) -> list[dict[str, Any]]:
    state_filter = (state or "").strip().upper()
    risk_filter = (risk or "").strip().upper()
    level_filter = (potential_level or "").strip().upper()
    filtered: list[dict[str, Any]] = []

    for record in records:
        if state_filter and state_filter != "ALL":
            if str(record["state"]).strip().upper() != state_filter:
                continue
        if risk_filter and risk_filter != "ALL":
            if str(record["risk"]).strip().upper() != risk_filter:
                continue
        if level_filter and level_filter != "ALL":
            if str(record["potential_level"]).strip().upper() != level_filter:
                continue
        filtered.append(record)
    return filtered


def _value_counts_dict(
    series: pd.Series,
    *,
    preferred_order: list[str] | None = None,
    exclude_blank: bool = False,
) -> dict[str, int]:
    normalized = series.astype("string").fillna("")
    if exclude_blank:
        normalized = normalized[normalized.str.strip() != ""]
    counts = normalized.value_counts(dropna=False).to_dict()
    counts_clean = {str(key): int(value) for key, value in counts.items() if str(key) != ""}

    if not preferred_order:
        return dict(sorted(counts_clean.items(), key=lambda item: item[0]))
    ordered: dict[str, int] = {}
    for key in preferred_order:
        ordered[key] = int(counts_clean.pop(key, 0))
    for key, value in sorted(counts_clean.items(), key=lambda item: item[0]):
        ordered[key] = value
    return ordered


def _sorted_unique(series: pd.Series, *, exclude_blank: bool) -> list[str]:
    normalized = series.astype("string").fillna("").str.strip()
    if exclude_blank:
        normalized = normalized[normalized != ""]
    return sorted(set(str(value) for value in normalized.tolist()))


def _build_risk_list(risk_series: pd.Series) -> list[str]:
    present = {str(value) for value in risk_series.astype("string").fillna("").tolist() if str(value)}
    ordered = [risk for risk in SUPPORTED_RISK_VALUES if risk in present]
    extras = sorted(present.difference(set(SUPPORTED_RISK_VALUES)))
    return ordered + extras


def _build_potential_level_list(level_series: pd.Series) -> list[str]:
    preferred = ["HIGH", "MEDIUM", "LOW", "OTHER"]
    present = {str(value).upper() for value in level_series.astype("string").fillna("").tolist() if str(value)}
    ordered = [level for level in preferred if level in present]
    extras = sorted(present.difference(set(preferred)))
    return ordered + extras


def _safe_number(value: object) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Unable to decode CSV output file: {path.name}")
