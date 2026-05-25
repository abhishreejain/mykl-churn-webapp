"""Post-scoring potential enrichment using historical 2024-2025 scan windows."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from churn_model.cleaning import normalize_mobile
from churn_model.config import ProjectConfig
from churn_model.schema import MONTH_COLUMNS

LOGGER = logging.getLogger(__name__)

POTENTIAL_LOOKUP_FILENAME = "potential_lookup_2024_2025.parquet"
HISTORY_START = pd.Timestamp("2024-01-01")
HISTORY_END = pd.Timestamp("2025-12-01")
SCORED_INPUT_COLUMNS = [
    "State",
    "Customer name",
    "Customer mobile number",
    "Churn probability",
    "Risk",
]
SCORED_OUTPUT_COLUMNS = [
    "State",
    "Customer name",
    "Customer mobile number",
    "Churn probability",
    "Risk",
    "Potential",
    "Potential Band",
]


def add_potential_to_scored_file(
    scored_input_path: Path,
    scored_output_path: Path,
    cfg: ProjectConfig | None = None,
    lookup_path: Path | None = None,
    report_path: Path | None = None,
    rules_report_path: Path | None = None,
    allow_lookup_build: bool = True,
) -> Path:
    """Append Potential and Potential Band to an already-scored file.

    Contract:
    - Input schema must be exactly `SCORED_INPUT_COLUMNS` in the same order.
    - Existing churn fields are preserved from input and are not recomputed.
    - Only `Potential` and `Potential Band` are appended.
    """
    scored = _read_csv_with_fallback(scored_input_path)
    _validate_scored_input_schema(scored)
    scored = scored.copy()
    scored["__row_order"] = np.arange(len(scored))
    scored["__mobile_id"] = scored["Customer mobile number"].map(normalize_mobile)

    if lookup_path is None and cfg is None:
        raise ValueError(
            "Potential enrichment requires `lookup_path` at runtime. "
            "Provide a packaged potential lookup artifact."
        )
    lookup_file = lookup_path or (cfg.path("paths.production_artifacts_dir") / POTENTIAL_LOOKUP_FILENAME)
    lookup = build_or_load_potential_lookup(
        cfg,
        lookup_file,
        report_path=report_path,
        rules_report_path=rules_report_path,
        allow_lookup_build=allow_lookup_build,
    )
    if not lookup.empty:
        lookup_indexed = lookup.set_index("mobile_id")
        scored["Potential"] = scored["__mobile_id"].map(lookup_indexed["Potential"])
        scored["Potential Band"] = scored["__mobile_id"].map(lookup_indexed["Potential Band"])
    else:
        scored["Potential"] = pd.NA
        scored["Potential Band"] = pd.NA

    output = scored.sort_values("__row_order").drop(columns=["__row_order", "__mobile_id"])
    output = output[SCORED_OUTPUT_COLUMNS]
    scored_output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(scored_output_path, index=False)
    LOGGER.info("Wrote enriched scored output with potential fields to %s", scored_output_path)
    return scored_output_path


def build_or_load_potential_lookup(
    cfg: ProjectConfig | None,
    lookup_path: Path,
    report_path: Path | None = None,
    rules_report_path: Path | None = None,
    allow_lookup_build: bool = True,
) -> pd.DataFrame:
    if lookup_path.exists():
        LOGGER.info("Loading existing potential lookup: %s", lookup_path)
        return pd.read_parquet(lookup_path)
    if not allow_lookup_build:
        raise FileNotFoundError(
            "Packaged potential lookup artifact not found. "
            f"Expected at: {lookup_path}. "
            "Runtime enrichment is configured to disallow building lookup from historical files."
        )
    if cfg is None:
        raise ValueError(
            "Cannot build potential lookup without config. "
            "Pass `cfg` for build-time lookup generation, or provide packaged lookup for runtime."
        )
    return build_potential_lookup(cfg, lookup_path, report_path=report_path, rules_report_path=rules_report_path)


def build_potential_lookup(
    cfg: ProjectConfig,
    lookup_path: Path,
    report_path: Path | None = None,
    rules_report_path: Path | None = None,
    summary_csv_path: Path | None = None,
) -> pd.DataFrame:
    """Build potential lookup from strict consecutive 6-month windows in 2024-2025."""
    history, history_source = _load_history_panel_for_potential(cfg)
    filtered = history[(history["month_date"] >= HISTORY_START) & (history["month_date"] <= HISTORY_END)].copy()
    filtered["scan_points"] = pd.to_numeric(filtered["scan_points"], errors="coerce").fillna(0.0)
    filtered["mobile_id"] = filtered["mobile_id"].map(normalize_mobile)
    filtered = filtered[filtered["mobile_id"].notna()].copy()

    lookup, total_influencers, eligible_influencers = _compute_lookup_from_filtered_history(filtered)
    no_valid_window_count = total_influencers - eligible_influencers
    lookup_path.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_parquet(lookup_path, index=False)
    LOGGER.info("Wrote potential lookup to %s", lookup_path)

    report = report_path or (cfg.path("paths.reports_dir") / "POTENTIAL_LOOKUP_BUILD.md")
    rules_report = rules_report_path or (cfg.path("paths.reports_dir") / "POTENTIAL_BAND_RULES.md")
    summary_csv = summary_csv_path or (cfg.path("paths.reports_dir") / "POTENTIAL_LOOKUP_SUMMARY.csv")
    _write_lookup_build_report(
        report_path=report,
        history_source=history_source,
        lookup_path=lookup_path,
        rows_in_history=len(history),
        rows_in_filtered_history=len(filtered),
        total_influencers=total_influencers,
        eligible_influencers=eligible_influencers,
        no_valid_window_count=no_valid_window_count,
        lookup_rows=len(lookup),
        lookup=lookup,
    )
    _write_lookup_summary_csv(
        path=summary_csv,
        history_source=history_source,
        total_influencers=total_influencers,
        eligible_influencers=eligible_influencers,
        no_valid_window_count=no_valid_window_count,
        lookup=lookup,
    )
    _write_potential_band_rules_report(rules_report)
    return lookup


def _compute_lookup_from_filtered_history(filtered: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    total_influencers = int(filtered["mobile_id"].nunique())
    if filtered.empty or total_influencers == 0:
        return pd.DataFrame(
            columns=[
                "mobile_id",
                "max_continuous_6m_sum_2024_2025",
                "best_window_start_month",
                "best_window_end_month",
                "Potential",
                "Potential Band",
            ]
        ), 0, 0

    monthly = (
        filtered.groupby(["mobile_id", "month_date"], as_index=False)["scan_points"]
        .sum()
        .sort_values(["mobile_id", "month_date"])
        .reset_index(drop=True)
    )
    monthly["month_ordinal"] = monthly["month_date"].map(_month_ordinal)
    monthly["prev_ordinal"] = monthly.groupby("mobile_id")["month_ordinal"].shift(1)
    monthly["segment_break"] = (
        monthly["prev_ordinal"].isna() | ((monthly["month_ordinal"] - monthly["prev_ordinal"]) != 1)
    )
    monthly["segment_id"] = monthly["segment_break"].cumsum()
    monthly["rolling_6m_sum"] = monthly.groupby("segment_id")["scan_points"].transform(
        lambda s: s.rolling(window=6, min_periods=6).sum()
    )
    valid = monthly[monthly["rolling_6m_sum"].notna()].copy()
    if valid.empty:
        return pd.DataFrame(
            columns=[
                "mobile_id",
                "max_continuous_6m_sum_2024_2025",
                "best_window_start_month",
                "best_window_end_month",
                "Potential",
                "Potential Band",
            ]
        ), total_influencers, 0

    valid["best_window_end_month"] = pd.to_datetime(valid["month_date"]).dt.strftime("%Y-%m")
    valid["best_window_start_month"] = (
        pd.to_datetime(valid["month_date"]) - pd.DateOffset(months=5)
    ).dt.strftime("%Y-%m")
    per_mobile_max = (
        valid.groupby("mobile_id", as_index=False)["rolling_6m_sum"]
        .max()
        .rename(columns={"rolling_6m_sum": "max_continuous_6m_sum_2024_2025"})
    )
    with_max = valid.merge(
        per_mobile_max,
        how="inner",
        on="mobile_id",
    )
    with_max = with_max[np.isclose(with_max["rolling_6m_sum"], with_max["max_continuous_6m_sum_2024_2025"])].copy()
    # Deterministic tie-breaker: earliest end month.
    best = with_max.sort_values(["mobile_id", "month_date"]).drop_duplicates("mobile_id", keep="first")
    best["Potential"] = best["max_continuous_6m_sum_2024_2025"] * 2.0
    best["Potential Band"] = best["Potential"].map(assign_potential_band)

    lookup = best[
        [
            "mobile_id",
            "max_continuous_6m_sum_2024_2025",
            "best_window_start_month",
            "best_window_end_month",
            "Potential",
            "Potential Band",
        ]
    ].reset_index(drop=True)
    return lookup, total_influencers, int(len(lookup))


def assign_potential_band(potential: float | int | None) -> str | pd.NA:
    if potential is None or pd.isna(potential):
        return pd.NA
    value = float(potential)
    if value < 12000:
        return "<12k"
    if value < 15000:
        return "12-15k"
    if value <= 25000:
        return "15-25k"
    return ">25k"


def _max_strict_consecutive_six_month_total(monthly: pd.DataFrame) -> tuple[float, str, str] | None:
    if monthly.empty or len(monthly) < 6:
        return None
    ordinals = monthly["month_date"].map(_month_ordinal).to_numpy()
    values = monthly["scan_points"].to_numpy(dtype=float)
    best_total: float | None = None
    best_start: pd.Timestamp | None = None
    best_end: pd.Timestamp | None = None
    for start_idx in range(0, len(monthly) - 5):
        end_idx = start_idx + 5
        window_ord = ordinals[start_idx : end_idx + 1]
        if not np.all(np.diff(window_ord) == 1):
            continue
        total = float(np.nansum(values[start_idx : end_idx + 1]))
        if best_total is None or total > best_total:
            best_total = total
            best_start = pd.Timestamp(monthly.iloc[start_idx]["month_date"])
            best_end = pd.Timestamp(monthly.iloc[end_idx]["month_date"])
    if best_total is None or best_start is None or best_end is None:
        return None
    return best_total, best_start.strftime("%Y-%m"), best_end.strftime("%Y-%m")


def _month_ordinal(value: pd.Timestamp) -> int:
    return int(value.year) * 12 + int(value.month)


def _load_history_panel_for_potential(cfg: ProjectConfig) -> tuple[pd.DataFrame, str]:
    panel_path = cfg.path("paths.monthly_panel")
    if panel_path.exists():
        LOGGER.info("Loading monthly panel for potential lookup: %s", panel_path)
        panel = pd.read_parquet(panel_path) if panel_path.suffix.lower() == ".parquet" else pd.read_csv(panel_path)
        normalized = _normalize_panel_columns(panel)
        return normalized, f"monthly_panel:{panel_path}"

    LOGGER.warning("Monthly panel not found at %s; falling back to cleaned yearly datasets.", panel_path)
    yearly = _load_cleaned_yearly_fallback(cfg.path("paths.processed_data_dir"))
    return yearly, f"cleaned_yearly_fallback:{cfg.path('paths.processed_data_dir')}"


def _normalize_panel_columns(panel: pd.DataFrame) -> pd.DataFrame:
    work = panel.copy()
    if "month_date" not in work.columns:
        raise ValueError("Monthly panel is missing `month_date` required for potential enrichment.")
    if "scan_points" not in work.columns:
        raise ValueError("Monthly panel is missing `scan_points` required for potential enrichment.")
    if "mobile_id" not in work.columns:
        if "influencer_id" in work.columns:
            work["mobile_id"] = work["influencer_id"].astype("string")
        else:
            raise ValueError("Monthly panel is missing `mobile_id` and `influencer_id`; cannot build potential lookup.")

    result = pd.DataFrame(
        {
            "mobile_id": work["mobile_id"],
            "month_date": pd.to_datetime(work["month_date"], errors="coerce"),
            "scan_points": pd.to_numeric(work["scan_points"], errors="coerce"),
        }
    )
    return result[result["month_date"].notna()].copy()


def _load_cleaned_yearly_fallback(processed_dir: Path) -> pd.DataFrame:
    files = sorted(processed_dir.glob("yearly_*_cleaned.csv"))
    files = [path for path in files if path.stem in {"yearly_2024_cleaned", "yearly_2025_cleaned"}]
    if not files:
        raise FileNotFoundError(
            "Monthly panel unavailable and cleaned yearly fallback files were not found for 2024/2025 "
            f"under {processed_dir}"
        )
    parts: list[pd.DataFrame] = []
    for path in files:
        year = int(path.stem.split("_")[1])
        frame = pd.read_csv(path)
        if "mobile_id" not in frame.columns and "MobileNo1" in frame.columns:
            frame["mobile_id"] = frame["MobileNo1"].map(normalize_mobile)
        long = frame.melt(
            id_vars=["mobile_id"],
            value_vars=MONTH_COLUMNS,
            var_name="month_name",
            value_name="scan_points",
        )
        month_map = {name: idx for idx, name in enumerate(MONTH_COLUMNS, start=1)}
        long["month_date"] = pd.to_datetime(
            {
                "year": year,
                "month": long["month_name"].map(month_map),
                "day": 1,
            },
            errors="coerce",
        )
        parts.append(long[["mobile_id", "month_date", "scan_points"]])
    return pd.concat(parts, ignore_index=True)


def _validate_scored_input_schema(scored: pd.DataFrame) -> None:
    actual = [str(column) for column in scored.columns]
    if actual != SCORED_INPUT_COLUMNS:
        raise ValueError(
            "Scored input schema mismatch for potential enrichment. "
            f"Expected exactly columns in order: {SCORED_INPUT_COLUMNS}. "
            f"Found: {actual}"
        )


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Unable to decode CSV input file: {path}")


def _write_lookup_build_report(
    report_path: Path,
    history_source: str,
    lookup_path: Path,
    rows_in_history: int,
    rows_in_filtered_history: int,
    total_influencers: int,
    eligible_influencers: int,
    no_valid_window_count: int,
    lookup_rows: int,
    lookup: pd.DataFrame,
) -> None:
    max6_col = "max_continuous_6m_sum_2024_2025"
    if lookup.empty:
        max6_stats = {"min": pd.NA, "median": pd.NA, "max": pd.NA}
        potential_stats = {"min": pd.NA, "median": pd.NA, "max": pd.NA}
        sample_text = "_No eligible influencers with valid strict 6-month windows._"
    else:
        max6 = pd.to_numeric(lookup[max6_col], errors="coerce")
        pot = pd.to_numeric(lookup["Potential"], errors="coerce")
        max6_stats = {"min": float(max6.min()), "median": float(max6.median()), "max": float(max6.max())}
        potential_stats = {"min": float(pot.min()), "median": float(pot.median()), "max": float(pot.max())}

        sample = (
            lookup.sort_values(["Potential", max6_col], ascending=False)
            .head(20)
            .copy()
        )
        sample["max_window_6m"] = sample["best_window_start_month"].astype(str) + " to " + sample["best_window_end_month"].astype(str)
        sample = sample[
            ["mobile_id", max6_col, "Potential", "max_window_6m"]
        ].rename(columns={"mobile_id": "canonical_mobile_id"})
        sample_text = _markdown_table_from_df(sample)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "# POTENTIAL_LOOKUP_BUILD\n\n"
        + f"- History source used: `{history_source}`\n"
        + "- History period filter: `2024-01-01` through `2025-12-01` inclusive.\n"
        + "- Window rule: strict consecutive 6-month windows only.\n"
        + "- Aggregation rule: monthly scan totals are summed inside each valid 6-month window.\n"
        + "- Missing scan values inside existing month rows are treated as `0` for window total calculations.\n"
        + "- Potential formula: `Potential = 2 * max_continuous_6m_sum_2024_2025`.\n"
        + "\n## Build Stats\n\n"
        + f"- Rows in source history: `{rows_in_history}`\n"
        + f"- Rows after 2024-2025 filter and canonical mobile filter: `{rows_in_filtered_history}`\n"
        + f"- Influencers considered: `{total_influencers}`\n"
        + f"- Influencers with at least one valid strict 6-month window: `{eligible_influencers}`\n"
        + f"- Influencers without any valid strict 6-month window: `{no_valid_window_count}`\n"
        + f"- Final lookup rows written: `{lookup_rows}`\n"
        + f"- Lookup artifact: `{lookup_path}`\n",
        encoding="utf-8",
    )
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## Distribution Statistics\n\n"
            + "### max_continuous_6m_sum_2024_2025\n\n"
            + f"- Min: `{max6_stats['min']}`\n"
            + f"- Median: `{max6_stats['median']}`\n"
            + f"- Max: `{max6_stats['max']}`\n\n"
            + "### Potential\n\n"
            + f"- Min: `{potential_stats['min']}`\n"
            + f"- Median: `{potential_stats['median']}`\n"
            + f"- Max: `{potential_stats['max']}`\n\n"
            + "## Sample Influencers (at least 20)\n\n"
            + sample_text
            + "\n"
        )


def _write_lookup_summary_csv(
    path: Path,
    history_source: str,
    total_influencers: int,
    eligible_influencers: int,
    no_valid_window_count: int,
    lookup: pd.DataFrame,
) -> None:
    max6_col = "max_continuous_6m_sum_2024_2025"
    if lookup.empty:
        row = {
            "history_source": history_source,
            "history_start": HISTORY_START.strftime("%Y-%m-%d"),
            "history_end": HISTORY_END.strftime("%Y-%m-%d"),
            "total_influencers_examined": total_influencers,
            "influencers_with_valid_consecutive_6m_window": eligible_influencers,
            "influencers_without_valid_consecutive_6m_window": no_valid_window_count,
            "max6m_sum_min": pd.NA,
            "max6m_sum_median": pd.NA,
            "max6m_sum_max": pd.NA,
            "potential_min": pd.NA,
            "potential_median": pd.NA,
            "potential_max": pd.NA,
        }
    else:
        max6 = pd.to_numeric(lookup[max6_col], errors="coerce")
        potential = pd.to_numeric(lookup["Potential"], errors="coerce")
        row = {
            "history_source": history_source,
            "history_start": HISTORY_START.strftime("%Y-%m-%d"),
            "history_end": HISTORY_END.strftime("%Y-%m-%d"),
            "total_influencers_examined": total_influencers,
            "influencers_with_valid_consecutive_6m_window": eligible_influencers,
            "influencers_without_valid_consecutive_6m_window": no_valid_window_count,
            "max6m_sum_min": float(max6.min()),
            "max6m_sum_median": float(max6.median()),
            "max6m_sum_max": float(max6.max()),
            "potential_min": float(potential.min()),
            "potential_median": float(potential.median()),
            "potential_max": float(potential.max()),
        }
    summary = pd.DataFrame([row])
    path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(path, index=False)


def _write_potential_band_rules_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# POTENTIAL_BAND_RULES\n\n"
        + "Potential band mapping:\n\n"
        + "- `Potential < 12000` => `<12k`\n"
        + "- `12000 <= Potential < 15000` => `12-15k`\n"
        + "- `15000 <= Potential <= 25000` => `15-25k`\n"
        + "- `Potential > 25000` => `>25k`\n",
        encoding="utf-8",
    )


def _markdown_table_from_df(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    columns = [str(col) for col in df.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in columns:
            value = row[col]
            if pd.isna(value):
                values.append("")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
