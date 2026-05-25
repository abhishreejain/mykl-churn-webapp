"""Feature engineering constrained to six scan values plus allowed fields."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCAN_FEATURE_COLUMNS = [f"scan_m{i}" for i in range(1, 7)]
WINDOW_SCAN_COLUMNS = [f"feature_scan_m{i}" for i in range(1, 7)]
MONTH_FEATURE_COLUMNS = [f"month_{i}" for i in range(1, 7)]

NUMERIC_FEATURES = [
    *MONTH_FEATURE_COLUMNS,
    "sum_6m",
    "avg_6m",
    "median_6m",
    "min_6m",
    "max_6m",
    "std_6m",
    "active_months_last_2",
    "active_months_last_3",
    "active_months_last_4",
    "active_months_last_5",
    "active_months_last_6",
    "pct_change_last_3_vs_prev_3",
    "first_3m_sum",
    "last_3m_sum",
    "last_2m_sum",
    "last_1m",
    "ratio_last3_first3",
    "ratio_last2_last4",
    "delta_last3_first3",
    "delta_last2_last3",
    "trend_last_3_vs_prev_3",
    "month6_vs_month1_ratio",
    "linear_trend_slope_6m",
    "avg_month_on_month_change",
    "positive_change_count",
    "negative_change_count",
    "zero_month_count",
    "recent_consecutive_zero_count",
    "active_month_count",
    "coefficient_of_variation",
    "share_recent3_of_total6",
    "volatility_std_mom_change",
    "volatility_range_6m",
    "volatility_mean_abs_mom_change",
    "volatility_max_abs_mom_change",
]

CATEGORICAL_FEATURES = ["state"]
FEATURE_COLUMNS = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
BLOCKED_PREDICTIVE_COLUMNS = {
    "Name",
    "customer_name",
    "MobileNo1",
    "mobile_id",
    "customer_mobile_number",
    "original_mobile_number",
    "original_customer_name",
    "influencer_id",
}


@dataclass(frozen=True)
class FeatureSpec:
    """Feature transformation contract shared by training and scoring."""

    include_state: bool = True
    state_unknown_value: str = "UNKNOWN"
    safe_division_fill_value: float | None = None

    @property
    def feature_columns(self) -> list[str]:
        return FEATURE_COLUMNS if self.include_state else NUMERIC_FEATURES


FEATURE_DEFINITIONS: list[dict[str, str]] = [
    {"feature": "month_1..month_6", "type": "numeric", "definition": "Raw ordered scan values, oldest to newest."},
    {"feature": "sum_6m", "type": "numeric", "definition": "Sum of month_1 through month_6."},
    {"feature": "avg_6m", "type": "numeric", "definition": "Mean of month_1 through month_6."},
    {"feature": "median_6m", "type": "numeric", "definition": "Median of month_1 through month_6."},
    {"feature": "min_6m", "type": "numeric", "definition": "Minimum scan value in the six-month window."},
    {"feature": "max_6m", "type": "numeric", "definition": "Maximum scan value in the six-month window."},
    {"feature": "std_6m", "type": "numeric", "definition": "Population standard deviation across the six scan values."},
    {
        "feature": "active_months_last_N",
        "type": "numeric",
        "definition": "Count of months with scan value > 0 over the last N months for N in {2,3,4,5,6}.",
    },
    {
        "feature": "pct_change_last_3_vs_prev_3",
        "type": "numeric",
        "definition": "(last_3m_sum - first_3m_sum) / first_3m_sum with safe division.",
    },
    {"feature": "first_3m_sum", "type": "numeric", "definition": "month_1 + month_2 + month_3."},
    {"feature": "last_3m_sum", "type": "numeric", "definition": "month_4 + month_5 + month_6."},
    {"feature": "last_2m_sum", "type": "numeric", "definition": "month_5 + month_6."},
    {"feature": "last_1m", "type": "numeric", "definition": "month_6."},
    {"feature": "ratio_last3_first3", "type": "numeric", "definition": "last_3m_sum / first_3m_sum with safe division."},
    {
        "feature": "ratio_last2_last4",
        "type": "numeric",
        "definition": "(month_5 + month_6) / (month_3 + month_4 + month_5 + month_6) with safe division.",
    },
    {"feature": "delta_last3_first3", "type": "numeric", "definition": "last_3m_sum - first_3m_sum."},
    {"feature": "delta_last2_last3", "type": "numeric", "definition": "(month_5 + month_6) - (month_4 + month_5 + month_6)."},
    {"feature": "trend_last_3_vs_prev_3", "type": "numeric", "definition": "Average of months 4-6 minus average of months 1-3."},
    {"feature": "month6_vs_month1_ratio", "type": "numeric", "definition": "month_6 / month_1 with safe division."},
    {"feature": "linear_trend_slope_6m", "type": "numeric", "definition": "Least-squares slope over month index 1..6."},
    {"feature": "avg_month_on_month_change", "type": "numeric", "definition": "Mean of consecutive month differences."},
    {"feature": "positive_change_count", "type": "numeric", "definition": "Count of consecutive month differences greater than zero."},
    {"feature": "negative_change_count", "type": "numeric", "definition": "Count of consecutive month differences less than zero."},
    {"feature": "zero_month_count", "type": "numeric", "definition": "Count of months in the six-month window equal to zero."},
    {"feature": "recent_consecutive_zero_count", "type": "numeric", "definition": "Number of trailing consecutive zero months ending at month_6."},
    {"feature": "active_month_count", "type": "numeric", "definition": "Count of months in the six-month window with scan value > 0."},
    {"feature": "coefficient_of_variation", "type": "numeric", "definition": "std_6m / avg_6m with safe division."},
    {"feature": "share_recent3_of_total6", "type": "numeric", "definition": "last_3m_sum / sum_6m with safe division."},
    {"feature": "volatility_std_mom_change", "type": "numeric", "definition": "Population standard deviation of month-on-month changes."},
    {"feature": "volatility_range_6m", "type": "numeric", "definition": "max_6m - min_6m."},
    {"feature": "volatility_mean_abs_mom_change", "type": "numeric", "definition": "Mean absolute month-on-month change."},
    {"feature": "volatility_max_abs_mom_change", "type": "numeric", "definition": "Maximum absolute month-on-month change."},
    {"feature": "state", "type": "categorical", "definition": "Allowed state field from the same input file; encoded by the model pipeline."},
]


def build_features(windows: pd.DataFrame, include_state: bool = True) -> pd.DataFrame:
    """Build train/score-parity features from six ordered scan values and optional state."""
    return FeatureTransformer(FeatureSpec(include_state=include_state)).transform(windows)


class FeatureTransformer:
    """Reusable deterministic transformer for training and scoring."""

    def __init__(self, spec: FeatureSpec | None = None) -> None:
        self.spec = spec or FeatureSpec()

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        scan_columns = resolve_scan_columns(data)
        scans = data[scan_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
        scans.columns = MONTH_FEATURE_COLUMNS
        values = scans.to_numpy(dtype=float)
        diffs = np.diff(values, axis=1)

        features = pd.DataFrame(index=data.index)
        for column in MONTH_FEATURE_COLUMNS:
            features[column] = scans[column]

        first3 = scans[["month_1", "month_2", "month_3"]].sum(axis=1)
        last3 = scans[["month_4", "month_5", "month_6"]].sum(axis=1)
        last2 = scans[["month_5", "month_6"]].sum(axis=1)
        last4 = scans[["month_3", "month_4", "month_5", "month_6"]].sum(axis=1)

        features["sum_6m"] = scans.sum(axis=1)
        features["avg_6m"] = scans.mean(axis=1)
        features["median_6m"] = scans.median(axis=1)
        features["min_6m"] = scans.min(axis=1)
        features["max_6m"] = scans.max(axis=1)
        features["std_6m"] = scans.std(axis=1, ddof=0)
        for n in [2, 3, 4, 5, 6]:
            features[f"active_months_last_{n}"] = (scans.iloc[:, -n:] > 0).sum(axis=1)
        features["pct_change_last_3_vs_prev_3"] = _safe_divide(last3 - first3, first3, self.spec.safe_division_fill_value)
        features["first_3m_sum"] = first3
        features["last_3m_sum"] = last3
        features["last_2m_sum"] = last2
        features["last_1m"] = scans["month_6"]
        features["ratio_last3_first3"] = _safe_divide(last3, first3, self.spec.safe_division_fill_value)
        features["ratio_last2_last4"] = _safe_divide(last2, last4, self.spec.safe_division_fill_value)
        features["delta_last3_first3"] = last3 - first3
        features["delta_last2_last3"] = last2 - last3
        features["trend_last_3_vs_prev_3"] = (last3 / 3.0) - (first3 / 3.0)
        features["month6_vs_month1_ratio"] = _safe_divide(scans["month_6"], scans["month_1"], self.spec.safe_division_fill_value)
        features["linear_trend_slope_6m"] = _linear_slope(values)
        features["avg_month_on_month_change"] = diffs.mean(axis=1)
        features["positive_change_count"] = (diffs > 0).sum(axis=1)
        features["negative_change_count"] = (diffs < 0).sum(axis=1)
        features["zero_month_count"] = (scans == 0).sum(axis=1)
        features["recent_consecutive_zero_count"] = _trailing_zero_count(values)
        features["active_month_count"] = (scans > 0).sum(axis=1)
        features["coefficient_of_variation"] = _safe_divide(features["std_6m"], features["avg_6m"], self.spec.safe_division_fill_value)
        features["share_recent3_of_total6"] = _safe_divide(last3, features["sum_6m"], self.spec.safe_division_fill_value)
        features["volatility_std_mom_change"] = diffs.std(axis=1, ddof=0)
        features["volatility_range_6m"] = features["max_6m"] - features["min_6m"]
        features["volatility_mean_abs_mom_change"] = np.abs(diffs).mean(axis=1)
        features["volatility_max_abs_mom_change"] = np.abs(diffs).max(axis=1)

        if self.spec.include_state:
            features["state"] = resolve_state_series(data).fillna(self.spec.state_unknown_value).astype("string")

        features = features[self.spec.feature_columns]
        assert_no_blocked_predictive_columns(features)
        return features


def resolve_scan_columns(data: pd.DataFrame) -> list[str]:
    if all(column in data.columns for column in SCAN_FEATURE_COLUMNS):
        return SCAN_FEATURE_COLUMNS
    if all(column in data.columns for column in WINDOW_SCAN_COLUMNS):
        return WINDOW_SCAN_COLUMNS
    if all(column in data.columns for column in MONTH_FEATURE_COLUMNS):
        return MONTH_FEATURE_COLUMNS
    raise ValueError(
        "Input must contain exactly one supported six-month scan set: "
        f"{SCAN_FEATURE_COLUMNS}, {WINDOW_SCAN_COLUMNS}, or {MONTH_FEATURE_COLUMNS}"
    )


def resolve_state_series(data: pd.DataFrame) -> pd.Series:
    for column in ["state", "State", "original_state"]:
        if column in data.columns:
            return data[column].astype("string").str.strip().str.upper()
    return pd.Series(pd.NA, index=data.index, dtype="string")


def assert_no_blocked_predictive_columns(features: pd.DataFrame) -> None:
    blocked = sorted(BLOCKED_PREDICTIVE_COLUMNS.intersection(features.columns))
    if blocked:
        raise ValueError(f"Blocked predictive columns present in feature output: {blocked}")


def feature_manifest(include_state: bool = True) -> dict[str, Any]:
    spec = FeatureSpec(include_state=include_state)
    return {
        "version": 1,
        "allowed_predictive_inputs": {
            "scan_values": "Six ordered monthly scan values only, oldest to newest.",
            "state": include_state,
            "derived_from_scan_values": True,
        },
        "blocked_predictive_inputs": sorted(BLOCKED_PREDICTIVE_COLUMNS),
        "accepted_scan_column_sets": [SCAN_FEATURE_COLUMNS, WINDOW_SCAN_COLUMNS, MONTH_FEATURE_COLUMNS],
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES if include_state else [],
        "feature_columns_in_order": spec.feature_columns,
        "safe_division": "Returns null/NaN when denominator is zero.",
        "state_encoding": "Categorical state is emitted as `state`; model pipeline must encode it using training-fitted encoders.",
        "excluded_requested_features": {
            "trend_last_6_vs_prev_6": "Excluded because a literal previous-six-month comparison would require older history outside the six scoring months."
        },
        "definitions": FEATURE_DEFINITIONS,
    }


def write_feature_manifest(path: Path, include_state: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_manifest(include_state), indent=2), encoding="utf-8")
    return path


def write_feature_definitions_report(path: Path, include_state: bool = True) -> Path:
    manifest = feature_manifest(include_state)
    lines = [
        "# Engineered Feature Definitions",
        "## Contract",
        "- Predictive inputs are limited to six ordered scan values, `state`, and values derived from those six scans.",
        "- Raw customer name, raw mobile number, cleaned mobile identifier, older history, and future information are not predictive features.",
        "- The same `FeatureTransformer` is used for training and scoring to preserve exact feature parity.",
        "- Safe division returns null/NaN when the denominator is zero.",
        "",
        "## Feature Columns in Model Order",
        "\n".join(f"- `{column}`" for column in manifest["feature_columns_in_order"]),
        "",
        "## Definitions",
        "| Feature | Type | Definition |",
        "|---|---|---|",
    ]
    for item in FEATURE_DEFINITIONS:
        if item["feature"] == "state" and not include_state:
            continue
        lines.append(f"| `{item['feature']}` | {item['type']} | {item['definition']} |")
    lines.extend(
        [
            "",
            "## Explicitly Excluded",
            "\n".join(f"- `{column}`" for column in manifest["blocked_predictive_inputs"]),
            "",
            "## Requested But Not Engineered",
            "- `trend_last_6_vs_prev_6`: excluded because a literal previous-six-month comparison would require older history outside the six input months.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _safe_divide(numerator: pd.Series, denominator: pd.Series, fill_value: float | None) -> pd.Series:
    numerator = pd.Series(numerator, copy=False)
    denominator = pd.Series(denominator, copy=False)
    result = numerator / denominator.replace({0: np.nan})
    result = result.replace([np.inf, -np.inf], np.nan)
    return result.fillna(fill_value) if fill_value is not None else result


def _linear_slope(values: np.ndarray) -> np.ndarray:
    x = np.arange(1, 7, dtype=float)
    x_centered = x - x.mean()
    denominator = float((x_centered**2).sum())
    y_centered = values - values.mean(axis=1, keepdims=True)
    return (y_centered @ x_centered) / denominator


def _trailing_zero_count(values: np.ndarray) -> np.ndarray:
    counts = np.zeros(values.shape[0], dtype=int)
    for column in range(values.shape[1] - 1, -1, -1):
        is_zero = values[:, column] == 0
        counts += is_zero & (counts == values.shape[1] - 1 - column)
    return counts
