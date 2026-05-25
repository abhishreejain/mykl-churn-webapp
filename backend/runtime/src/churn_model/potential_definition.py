"""Potential definition checkpoints."""

from __future__ import annotations

import pandas as pd

from churn_model.config import DecisionRequired, ProjectConfig


def add_potential_if_configured(windows: pd.DataFrame, cfg: ProjectConfig) -> pd.DataFrame:
    rule = cfg.get("business_rules.potential_definition")
    if not rule or rule.get("type") in (None, "", "TBD"):
        raise DecisionRequired(
            "Potential logic is not configured. Choose explicit potential rules before final prioritization."
        )
    if rule.get("type") == "explicit_column":
        column = rule.get("column")
        if column not in windows.columns:
            raise ValueError(f"Configured potential column not found: {column}")
        result = windows.copy()
        result["potential"] = result[column]
        return result
    raise DecisionRequired(f"Unsupported or incomplete potential rule: {rule}")


def potential_option_report(windows: pd.DataFrame) -> pd.DataFrame:
    feature_start = "feature_window_start_month" if "feature_window_start_month" in windows.columns else "feature_start"
    feature_end = "feature_window_end_month" if "feature_window_end_month" in windows.columns else "feature_end"
    report = windows[["mobile_id", feature_start, feature_end, "recent_status"]].copy()
    feature_cols = [f"feature_scan_m{i}" for i in range(1, 7)] if "feature_scan_m1" in windows.columns else [f"scan_m{i}" for i in range(1, 7)]
    report["scan_sum_6m"] = windows[feature_cols].sum(axis=1)
    report["scan_max_6m"] = windows[feature_cols].max(axis=1)
    report["scan_sum_recent_3m"] = windows[feature_cols[3:6]].sum(axis=1)
    return report
