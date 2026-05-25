"""Recent-status-aware prioritization.

The prioritization layer is intentionally separate from model scoring:

- `risk_score` remains the raw model probability.
- `recent_status` is derived from the latest three months of the six-month
  feature window, never from older history or future data.
- Operational prioritization is configured in `business_rules.yaml`.
- The code does not invent risk thresholds, active criteria, or potential bands.

Supported `business_rules.prioritization_strategy.type` values:

- `within_recent_status`: rank separately inside `recently_scanning` and
  `recently_inactive`.
- `recently_scanning_first`: create a combined operational order where
  `recently_scanning` is placed before `recently_inactive`, then rank by score
  within each segment.
- `custom_segment_order`: same as above, but requires an explicit
  `segment_order` list in config.
- `score_only`: keep raw model score and recent-status segment, but do not
  produce a cross-segment operational rank.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from churn_model.config import DecisionRequired, ProjectConfig


RECENT_STATUS_VALUES = ["recently_scanning", "recently_inactive"]


def derive_recent_status_from_six_months(df: pd.DataFrame, scan_columns: list[str]) -> pd.Series:
    """Derive recent status from months 4-6 of the six-month input window."""
    if len(scan_columns) != 6:
        raise ValueError("recent status requires exactly six ordered scan columns")
    missing = [column for column in scan_columns if column not in df.columns]
    if missing:
        raise ValueError(f"Cannot derive recent_status; missing scan columns: {missing}")
    recent_total = df[scan_columns[-3:]].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
    return pd.Series(
        np.where(recent_total > 0, "recently_scanning", "recently_inactive"),
        index=df.index,
        name="recent_status",
    )


def ensure_recent_status(df: pd.DataFrame, scan_columns: list[str] | None = None) -> pd.DataFrame:
    """Ensure `recent_status` exists and, when scans are available, matches months 4-6."""
    result = df.copy()
    if scan_columns is not None and all(column in result.columns for column in scan_columns):
        derived = derive_recent_status_from_six_months(result, scan_columns)
        if "recent_status" in result.columns:
            mismatch = result["recent_status"].astype(str) != derived.astype(str)
            if mismatch.any():
                raise ValueError(
                    f"recent_status mismatch for {int(mismatch.sum())} rows; "
                    "it must be derived from months 4-6 of the six-month feature window."
                )
        result["recent_status"] = derived
    elif "recent_status" not in result.columns:
        raise ValueError("recent_status is required, or six scan columns must be supplied to derive it")

    invalid = sorted(set(result["recent_status"].dropna().astype(str)) - set(RECENT_STATUS_VALUES))
    if invalid:
        raise ValueError(f"Unexpected recent_status values: {invalid}")
    return result


def apply_prioritization(
    scored: pd.DataFrame,
    cfg: ProjectConfig,
    score_column: str = "risk_score",
    scan_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Apply configured operational prioritization without changing raw model score."""
    if score_column not in scored.columns:
        raise ValueError(f"{score_column} is required for prioritization")
    rule = cfg.get("business_rules.prioritization_strategy")
    if not isinstance(rule, dict) or rule.get("type") in (None, "", "TBD"):
        raise DecisionRequired("`business_rules.prioritization_strategy.type` must be explicitly configured")

    result = ensure_recent_status(scored, scan_columns)
    result["raw_model_probability"] = result[score_column]
    result["operational_priority_segment"] = result["recent_status"]
    strategy_type = rule["type"]

    if strategy_type == "within_recent_status":
        result["rank_within_recent_status"] = _rank_within_segment(result, score_column)
        result["operational_rank"] = pd.NA
        result["prioritization_strategy"] = strategy_type
        return result.sort_values(["recent_status", "rank_within_recent_status"]).reset_index(drop=True)

    if strategy_type == "recently_scanning_first":
        return _rank_with_segment_order(
            result,
            score_column,
            segment_order=["recently_scanning", "recently_inactive"],
            strategy_type=strategy_type,
        )

    if strategy_type == "custom_segment_order":
        segment_order = rule.get("segment_order")
        if not isinstance(segment_order, list) or sorted(segment_order) != sorted(RECENT_STATUS_VALUES):
            raise DecisionRequired(
                "`custom_segment_order` requires segment_order containing exactly "
                "`recently_scanning` and `recently_inactive`."
            )
        return _rank_with_segment_order(result, score_column, segment_order, strategy_type)

    if strategy_type == "score_only":
        result["rank_within_recent_status"] = _rank_within_segment(result, score_column)
        result["operational_rank"] = pd.NA
        result["prioritization_strategy"] = strategy_type
        return result.reset_index(drop=True)

    raise DecisionRequired(f"Unsupported prioritization strategy: {strategy_type}")


def rank_within_recent_status(scored: pd.DataFrame, score_column: str = "risk_score") -> pd.DataFrame:
    """Backward-compatible helper for segment-level ranking only."""
    result = ensure_recent_status(scored)
    if score_column not in result.columns:
        raise ValueError(f"{score_column} is required for prioritization")
    result["rank_within_recent_status"] = _rank_within_segment(result, score_column)
    return result.sort_values(["recent_status", "rank_within_recent_status"])


def _rank_with_segment_order(
    scored: pd.DataFrame,
    score_column: str,
    segment_order: list[str],
    strategy_type: str,
) -> pd.DataFrame:
    result = scored.copy()
    order_lookup = {segment: index for index, segment in enumerate(segment_order)}
    result["segment_order"] = result["recent_status"].map(order_lookup)
    if result["segment_order"].isna().any():
        raise ValueError("All rows must have a configured recent_status segment order")
    result["rank_within_recent_status"] = _rank_within_segment(result, score_column)
    result = result.sort_values(["segment_order", "rank_within_recent_status"]).reset_index(drop=True)
    result["operational_rank"] = np.arange(1, len(result) + 1)
    result["prioritization_strategy"] = strategy_type
    return result


def _rank_within_segment(scored: pd.DataFrame, score_column: str) -> pd.Series:
    return scored.groupby("recent_status")[score_column].rank(method="first", ascending=False)
