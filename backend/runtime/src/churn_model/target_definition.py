"""Target definition and label diagnostics.

Targets are created only from explicit configuration in
`business_rules.target_definition`. This module does not choose churn thresholds,
activity filters, decline percentages, or active/inactive criteria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from churn_model.config import DecisionRequired, ProjectConfig


FUTURE_COLUMNS = ["future_scan_m1", "future_scan_m2", "future_scan_m3"]
SUPPORTED_TARGET_TYPES = {"explicit_column", "future_total_rule", "decline_rule"}


def add_target_if_configured(windows: pd.DataFrame, cfg: ProjectConfig) -> pd.DataFrame:
    rule = cfg.get("business_rules.target_definition")
    return apply_target_definition(windows, rule)


def apply_target_definition(windows: pd.DataFrame, rule: dict[str, Any] | None) -> pd.DataFrame:
    if not rule or rule.get("type") in (None, "", "TBD"):
        raise DecisionRequired(
            "Target logic is not configured. Fill `business_rules.target_definition` "
            "before labeled datasets can be built."
        )
    rule_type = rule.get("type")
    if rule_type not in SUPPORTED_TARGET_TYPES:
        raise DecisionRequired(f"Unsupported target_definition.type: {rule_type}")

    labeled = windows.copy()
    if rule_type == "explicit_column":
        column = _require(rule, "column", "explicit_column")
        if column not in labeled.columns:
            raise DecisionRequired(f"Configured target column not found in windows: {column}")
        labeled["target"] = labeled[column].astype(int)
        return labeled

    if rule_type == "future_total_rule":
        threshold = _require(rule, "threshold", "future_total_rule")
        operator = _require(rule, "operator", "future_total_rule")
        source_column = rule.get("source_column", "future_3m_total")
        if source_column not in labeled.columns:
            raise DecisionRequired(f"Configured source_column not found in windows: {source_column}")
        labeled["target"] = _compare(labeled[source_column], operator, threshold).astype(int)
        return labeled

    if rule_type == "decline_rule":
        baseline_column = _require(rule, "baseline_column", "decline_rule")
        comparison_column = _require(rule, "comparison_column", "decline_rule")
        operator = _require(rule, "operator", "decline_rule")
        threshold = _require(rule, "threshold", "decline_rule")
        if baseline_column not in labeled.columns or comparison_column not in labeled.columns:
            raise DecisionRequired(
                f"Configured decline columns not found: baseline={baseline_column}, comparison={comparison_column}"
            )
        ratio = labeled[comparison_column] / labeled[baseline_column].replace({0: pd.NA})
        labeled["target_helper_decline_ratio"] = ratio
        labeled["target"] = _compare(ratio, operator, threshold).fillna(False).astype(int)
        return labeled

    raise DecisionRequired(f"Unsupported target rule: {rule}")


def write_label_diagnostics(
    dev_labeled: pd.DataFrame | None,
    test_labeled: pd.DataFrame | None,
    reports_dir: Path,
    rule: dict[str, Any] | None,
    blocked_reason: str | None = None,
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    if blocked_reason:
        _write_blocked_reports(reports_dir, rule, blocked_reason)
        return

    assert dev_labeled is not None and test_labeled is not None
    combined = pd.concat(
        [
            dev_labeled.assign(split="development"),
            test_labeled.assign(split="holdout_2025"),
        ],
        ignore_index=True,
    )
    overall = _label_distribution(combined, ["split"])
    by_status = _label_distribution(combined, ["split", "recent_status"])

    (reports_dir / "label_distribution_overall.md").write_text(
        "# Label Distribution Overall\n\n" + _markdown_table(overall) + "\n",
        encoding="utf-8",
    )
    (reports_dir / "label_distribution_by_recent_status.md").write_text(
        "# Label Distribution By Recent Status\n\n"
        + "Recent status is preserved as a reporting/prioritization segment and is not an additional target filter.\n\n"
        + _markdown_table(by_status)
        + "\n",
        encoding="utf-8",
    )
    (reports_dir / "target_application_audit.md").write_text(
        "# Target Application Audit\n\n"
        + "- Status: `PASS`\n"
        + f"- Target rule type: `{rule.get('type') if rule else None}`\n"
        + "- Extra active/inactive filters applied: `none`\n"
        + "- Development labels written to `data/modeling/development_windows_labeled.parquet`\n"
        + "- Holdout labels written to `data/modeling/test_windows_labeled_2025.parquet`\n"
        + "- `recent_status` preserved for reporting and prioritization.\n",
        encoding="utf-8",
    )


def target_option_report(windows: pd.DataFrame) -> pd.DataFrame:
    feature_start = "feature_window_start_month" if "feature_window_start_month" in windows.columns else "feature_start"
    feature_end = "feature_window_end_month" if "feature_window_end_month" in windows.columns else "feature_end"
    target_start = "target_window_start_month" if "target_window_start_month" in windows.columns else "target_start"
    target_end = "target_window_end_month" if "target_window_end_month" in windows.columns else "target_end"
    report = windows[[feature_start, feature_end, target_start, target_end, "recent_status"]].copy()
    feature_cols = [f"feature_scan_m{i}" for i in range(1, 7)] if "feature_scan_m1" in windows.columns else [f"scan_m{i}" for i in range(1, 7)]
    future_cols = [f"future_scan_m{i}" for i in range(1, 4)] if "future_scan_m1" in windows.columns else FUTURE_COLUMNS
    report["feature_6m_total"] = windows[feature_cols].sum(axis=1)
    report["future_3m_total"] = windows[future_cols].sum(axis=1)
    report["future_minus_feature_total"] = report["future_3m_total"] - report["feature_6m_total"]
    report["future_to_feature_total_ratio"] = (
        report["future_3m_total"] / report["feature_6m_total"].replace({0: pd.NA})
    )
    return report


def _write_blocked_reports(reports_dir: Path, rule: dict[str, Any] | None, blocked_reason: str) -> None:
    blocked = (
        "# Target Application Audit\n\n"
        + "- Status: `BLOCKED`\n"
        + f"- Target rule configured: `{rule}`\n"
        + f"- Reason: {blocked_reason}\n"
        + "- No labeled development or holdout datasets were written.\n"
        + "- No active/inactive filters were applied.\n"
    )
    (reports_dir / "target_application_audit.md").write_text(blocked, encoding="utf-8")
    (reports_dir / "label_distribution_overall.md").write_text(
        "# Label Distribution Overall\n\nStatus: `BLOCKED`. No target labels were created.\n",
        encoding="utf-8",
    )
    (reports_dir / "label_distribution_by_recent_status.md").write_text(
        "# Label Distribution By Recent Status\n\nStatus: `BLOCKED`. No target labels were created.\n",
        encoding="utf-8",
    )


def _label_distribution(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    counts = df.groupby([*group_cols, "target"], dropna=False).size().reset_index(name="row_count")
    totals = df.groupby(group_cols, dropna=False).size().reset_index(name="total_rows")
    result = counts.merge(totals, on=group_cols, how="left")
    result["label_share"] = result["row_count"] / result["total_rows"]
    return result


def _compare(series: pd.Series, operator: str, threshold: Any) -> pd.Series:
    threshold = float(threshold)
    if operator == "<":
        return series < threshold
    if operator == "<=":
        return series <= threshold
    if operator == ">":
        return series > threshold
    if operator == ">=":
        return series >= threshold
    if operator == "==":
        return series == threshold
    raise DecisionRequired(f"Unsupported target operator: {operator}")


def _require(rule: dict[str, Any], key: str, rule_type: str) -> Any:
    value = rule.get(key)
    if value in (None, "", "TBD"):
        raise DecisionRequired(f"`target_definition.{key}` is required for `{rule_type}`.")
    return value


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    columns = list(df.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)
