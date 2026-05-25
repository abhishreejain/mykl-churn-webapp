"""Production scoring helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from churn_model.cleaning import add_recent_status, find_duplicate_mobile_scan_conflicts, normalize_mobile
from churn_model.feature_engineering import SCAN_FEATURE_COLUMNS, build_features
from churn_model.config import ProjectConfig
from churn_model.io import read_scoring_input
from churn_model.modeling import load_model
from churn_model.schema import canonicalize_scoring_identifier_columns, detect_scoring_scan_columns


def prepare_scoring_input(
    df: pd.DataFrame,
    cfg: ProjectConfig,
    manual_scan_columns: list[str] | None = None,
    state_column: str | None = None,
    name_column: str | None = None,
    mobile_column: str | None = None,
) -> pd.DataFrame:
    work, resolved_ids = canonicalize_scoring_identifier_columns(
        df.copy(),
        state_column=state_column,
        name_column=name_column,
        mobile_column=mobile_column,
    )
    scan_candidates = detect_scoring_scan_columns(work, manual_scan_columns=manual_scan_columns)

    # Preserve left-to-right file order exactly as provided by detect_scoring_scan_columns:
    # month_1/scan_m1 is oldest and month_6/scan_m6 is most recent.
    for idx, column in enumerate(scan_candidates, start=1):
        work[f"scan_m{idx}"] = pd.to_numeric(work[column], errors="coerce")
    work["mobile_id"] = work["MobileNo1"].map(normalize_mobile)
    work = _resolve_scoring_duplicates(work, cfg)
    work = add_recent_status(work, SCAN_FEATURE_COLUMNS)
    work["scoring_scan_source_columns"] = ",".join(scan_candidates)
    work["scoring_identifier_source_columns"] = (
        f"State={resolved_ids['State']},Name={resolved_ids['Name']},MobileNo1={resolved_ids['MobileNo1']}"
    )
    return work


def score_file(
    input_path: Path,
    model_path: Path,
    output_path: Path,
    cfg: ProjectConfig,
    manual_scan_columns: list[str] | None = None,
    state_column: str | None = None,
    name_column: str | None = None,
    mobile_column: str | None = None,
) -> Path:
    raw = read_scoring_input(input_path)
    scoring_df = prepare_scoring_input(
        raw,
        cfg,
        manual_scan_columns=manual_scan_columns,
        state_column=state_column,
        name_column=name_column,
        mobile_column=mobile_column,
    )
    model = load_model(model_path)
    features = build_features(scoring_df)
    scoring_df["churn_probability"] = model.predict_proba(features)[:, 1]
    scoring_df["Risk"] = apply_probability_risk_labels(scoring_df["churn_probability"])
    final = pd.DataFrame(
        {
            "State": scoring_df["State"],
            "Customer name": scoring_df["Name"],
            "Customer mobile number": scoring_df["MobileNo1"],
            "Churn probability": scoring_df["churn_probability"],
            "Risk": scoring_df["Risk"],
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(output_path, index=False)
    return output_path


def apply_probability_risk_labels(churn_probability: pd.Series) -> pd.Series:
    """Map churn probability to final risk labels.

    Contract:
    - >= 0.85 => HIGH RISK
    - >= 0.50 and < 0.85 => MEDIUM RISK
    - < 0.50 => LOW RISK
    """
    score = pd.to_numeric(churn_probability, errors="coerce").fillna(0.0)
    return pd.Series(
        np.where(score >= 0.85, "HIGH RISK", np.where(score >= 0.50, "MEDIUM RISK", "LOW RISK")),
        index=churn_probability.index,
    )


def _resolve_scoring_duplicates(scored: pd.DataFrame, cfg: ProjectConfig) -> pd.DataFrame:
    """Handle duplicate canonical mobile IDs at scoring time.

    Policy is configured by `scoring.duplicate_mobile_policy` in config:
    - `error` (default): fail clearly with duplicate diagnostics.
    - `first_occurrence`: keep the first row per mobile_id in input order.
    """
    policy = str(cfg.get("scoring.duplicate_mobile_policy", "error")).strip().lower()
    dup_mask = scored["mobile_id"].notna() & scored["mobile_id"].duplicated(keep=False)
    if not dup_mask.any():
        return scored

    dup_df = scored.loc[dup_mask, ["mobile_id"]].copy()
    counts = dup_df.value_counts().reset_index(name="count").sort_values("count", ascending=False)
    sample = counts.head(10).to_dict(orient="records")
    conflicts = find_duplicate_mobile_scan_conflicts(scored, mobile_column="mobile_id", scan_columns=SCAN_FEATURE_COLUMNS)
    conflict_sample = conflicts[:10]

    if policy == "first_occurrence":
        if conflicts:
            raise ValueError(
                "Duplicate canonical mobile IDs have conflicting scan values in scoring input. "
                "Cannot apply `first_occurrence` safely when conflicts exist. "
                f"Conflict examples (top 10): {conflict_sample}. "
                "Fix upstream data or provide one unambiguous row per canonical mobile ID."
            )
        resolved = scored.drop_duplicates(subset=["mobile_id"], keep="first").copy()
        resolved["duplicate_resolution_applied"] = "first_occurrence_by_mobile_id"
        return resolved
    if conflicts:
        raise ValueError(
            "Duplicate canonical mobile IDs detected with conflicting scan values in scoring input. "
            "Default scoring policy is `error` to prevent ambiguous scoring. "
            f"Conflict examples (top 10): {conflict_sample}. "
            "Fix upstream data or set `scoring.duplicate_mobile_policy: first_occurrence` only when duplicate "
            "rows are exact scan-value duplicates."
        )
    raise ValueError(
        "Duplicate canonical mobile IDs detected after normalization in scoring input. "
        "Default scoring policy is `error` to prevent ambiguous duplicate scoring. "
        f"Duplicate examples (top 10): {sample}. "
        "Set `scoring.duplicate_mobile_policy: first_occurrence` only if business approves deterministic row resolution "
        "and duplicate rows carry identical scan values."
    )
