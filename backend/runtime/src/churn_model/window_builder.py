"""Rolling 6+3 window construction."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from churn_model.cleaning import add_recent_status

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowSpec:
    feature_months: int = 6
    horizon_months: int = 3


WINDOW_COLUMNS = [
    "influencer_id",
    "mobile_id",
    "state",
    "customer_name",
    "feature_window_start_month",
    "feature_window_end_month",
    "target_window_start_month",
    "target_window_end_month",
    "feature_scan_m1",
    "feature_scan_m2",
    "feature_scan_m3",
    "feature_scan_m4",
    "feature_scan_m5",
    "feature_scan_m6",
    "future_scan_m1",
    "future_scan_m2",
    "future_scan_m3",
    "feature_6m_total",
    "prior_3m_total",
    "recent_3m_total",
    "future_3m_total",
    "future_minus_recent",
    "future_over_recent_ratio",
    "zero_scans_last_3m_flag",
    "zero_scans_next_3m_flag",
    "recent_status",
    "recently_inactive",
    "recently_scanning",
    "feature_positive_month_count",
    "recent_positive_month_count",
    "future_positive_month_count",
    "future_any_scan_flag",
    "feature_start_year",
    "feature_end_year",
    "target_start_year",
    "target_end_year",
    "cross_year_feature_flag",
    "cross_year_target_flag",
    "cross_year_6_plus_3_flag",
]


@dataclass
class WindowBuildStats:
    total_candidate_windows: int = 0
    generated_windows: int = 0
    development_windows: int = 0
    holdout_windows: int = 0
    excluded_split_windows: int = 0
    skipped_nonconsecutive_windows: int = 0
    influencers_seen: int = 0
    influencers_with_windows: int = 0
    example_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    split_recent_status_counts: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    split_zero_last_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    split_zero_next_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    split_cross_year_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    split_recent_total_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    split_future_total_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))


def build_windows(panel: pd.DataFrame, spec: WindowSpec = WindowSpec()) -> pd.DataFrame:
    """In-memory window builder retained for tests and small datasets."""
    panel = _normalize_panel_columns(panel)
    required = {"mobile_id", "period", "scan_value", "State", "Name", "MobileNo1"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"Monthly panel is missing required columns: {sorted(missing)}")

    rows: list[dict[str, object]] = []
    work = panel.copy()
    work["period"] = pd.to_datetime(work["period"])
    work = work.sort_values(["mobile_id", "period"])

    for mobile_id, group in work.groupby("mobile_id", dropna=False):
        monthly = (
            group.groupby("period", as_index=False)
            .agg(
                scan_value=("scan_value", "sum"),
                State=("State", "last"),
                Name=("Name", "last"),
                MobileNo1=("MobileNo1", "last"),
            )
            .sort_values("period")
        )
        periods = monthly["period"].tolist()
        scans = monthly["scan_value"].tolist()
        for start in range(0, len(monthly) - spec.feature_months - spec.horizon_months + 1):
            candidate = _window_from_arrays(
                influencer_id=str(mobile_id),
                mobile_id=str(mobile_id),
                state=monthly.iloc[start + spec.feature_months - 1]["State"],
                customer_name=monthly.iloc[start + spec.feature_months - 1]["Name"],
                periods=periods,
                scans=scans,
                start=start,
                spec=spec,
            )
            if candidate is not None:
                rows.append(_legacy_window_row(candidate))

    windows = pd.DataFrame(rows)
    if not windows.empty:
        windows = add_recent_status(windows, [f"scan_m{i}" for i in range(1, spec.feature_months + 1)])
    return windows


def build_modeling_windows_from_panel(
    panel_path: Path,
    development_output_path: Path,
    test_output_path: Path,
    reports_dir: Path,
    spec: WindowSpec = WindowSpec(),
    holdout_year: int = 2025,
    batch_size: int = 250_000,
) -> WindowBuildStats:
    """Stream a sorted monthly parquet panel into unlabeled dev/test window parquet datasets."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    development_output_path.parent.mkdir(parents=True, exist_ok=True)
    test_output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = WindowBuildStats()
    dev_writer: pq.ParquetWriter | None = None
    test_writer: pq.ParquetWriter | None = None
    dev_batch: list[dict[str, object]] = []
    test_batch: list[dict[str, object]] = []

    carry = pd.DataFrame()
    parquet = pq.ParquetFile(panel_path)
    columns = [
        "influencer_id",
        "mobile_id",
        "original_state",
        "original_customer_name",
        "calendar_year",
        "calendar_month",
        "scan_points",
    ]

    for batch in parquet.iter_batches(columns=columns, batch_size=batch_size):
        frame = batch.to_pandas()
        if not carry.empty:
            frame = pd.concat([carry, frame], ignore_index=True)
        if frame.empty:
            continue
        last_id = frame["influencer_id"].iloc[-1]
        complete = frame[frame["influencer_id"] != last_id]
        carry = frame[frame["influencer_id"] == last_id].copy()
        dev_writer, test_writer, dev_batch, test_batch = _process_complete_groups(
            complete,
            spec,
            holdout_year,
            stats,
            development_output_path,
            test_output_path,
            dev_writer,
            test_writer,
            dev_batch,
            test_batch,
            batch_size,
        )

    if not carry.empty:
        dev_writer, test_writer, dev_batch, test_batch = _process_complete_groups(
            carry,
            spec,
            holdout_year,
            stats,
            development_output_path,
            test_output_path,
            dev_writer,
            test_writer,
            dev_batch,
            test_batch,
            batch_size,
        )

    if dev_batch:
        dev_writer = _flush_window_batch(dev_batch, development_output_path, dev_writer)
    if test_batch:
        test_writer = _flush_window_batch(test_batch, test_output_path, test_writer)
    if dev_writer is not None:
        dev_writer.close()
    if test_writer is not None:
        test_writer.close()

    _write_window_generation_summary(stats, reports_dir / "window_generation_summary.md", holdout_year)
    _write_recent_status_summary(stats, reports_dir / "recent_status_summary.md")
    LOGGER.info("Wrote development windows to %s", development_output_path)
    LOGGER.info("Wrote 2025 holdout windows to %s", test_output_path)
    return stats


def _process_complete_groups(
    frame: pd.DataFrame,
    spec: WindowSpec,
    holdout_year: int,
    stats: WindowBuildStats,
    development_output_path: Path,
    test_output_path: Path,
    dev_writer: pq.ParquetWriter | None,
    test_writer: pq.ParquetWriter | None,
    dev_batch: list[dict[str, object]],
    test_batch: list[dict[str, object]],
    batch_size: int,
) -> tuple[pq.ParquetWriter | None, pq.ParquetWriter | None, list[dict[str, object]], list[dict[str, object]]]:
    if frame.empty:
        return dev_writer, test_writer, dev_batch, test_batch
    for influencer_id, group in frame.groupby("influencer_id", sort=False, dropna=False):
        dev_rows, test_rows = _windows_for_influencer_frame(str(influencer_id), group, spec, holdout_year, stats)
        dev_batch.extend(dev_rows)
        test_batch.extend(test_rows)
        if len(dev_batch) >= batch_size:
            dev_writer = _flush_window_batch(dev_batch, development_output_path, dev_writer)
            dev_batch = []
        if len(test_batch) >= batch_size:
            test_writer = _flush_window_batch(test_batch, test_output_path, test_writer)
            test_batch = []
    return dev_writer, test_writer, dev_batch, test_batch


def _windows_for_influencer_frame(
    influencer_id: str,
    group: pd.DataFrame,
    spec: WindowSpec,
    holdout_year: int,
    stats: WindowBuildStats,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    stats.influencers_seen += 1
    group = group.sort_values(["calendar_year", "calendar_month"])
    years = group["calendar_year"].astype("int64").to_numpy()
    months = group["calendar_month"].astype("int64").to_numpy()
    ordinals = years * 12 + months
    scans = group["scan_points"].fillna(0).astype("float64").to_numpy()
    mobile_id = _last_nonblank(group["mobile_id"].tolist())
    state = _last_nonblank(group["original_state"].tolist())
    customer_name = _last_nonblank(group["original_customer_name"].tolist())

    dev_rows: list[dict[str, object]] = []
    test_rows: list[dict[str, object]] = []
    total_width = spec.feature_months + spec.horizon_months
    had_windows = False
    for start in range(0, len(group) - total_width + 1):
        stats.total_candidate_windows += 1
        window = _window_from_ordinals(
            influencer_id=influencer_id,
            mobile_id=mobile_id,
            state=state,
            customer_name=customer_name,
            ordinals=ordinals,
            scans=scans,
            start=start,
            spec=spec,
        )
        if window is None:
            stats.skipped_nonconsecutive_windows += 1
            continue
        had_windows = True
        stats.generated_windows += 1
        split = _split_for_window(window, holdout_year)
        if split == "development":
            dev_rows.append(window)
            stats.development_windows += 1
            _update_split_stats(stats, split, window)
        elif split == "holdout_2025":
            test_rows.append(window)
            stats.holdout_windows += 1
            _update_split_stats(stats, split, window)
        else:
            stats.excluded_split_windows += 1
        _update_example_counts(stats, window)
    if had_windows:
        stats.influencers_with_windows += 1
    return dev_rows, test_rows


def _window_from_ordinals(
    influencer_id: str,
    mobile_id: object,
    state: object,
    customer_name: object,
    ordinals: object,
    scans: object,
    start: int,
    spec: WindowSpec,
) -> dict[str, object] | None:
    total_width = spec.feature_months + spec.horizon_months
    window_ordinals = ordinals[start : start + total_width]
    if not bool(((window_ordinals[1:] - window_ordinals[:-1]) == 1).all()):
        return None
    feature_values = [float(value) for value in scans[start : start + spec.feature_months]]
    target_values = [
        float(value)
        for value in scans[start + spec.feature_months : start + spec.feature_months + spec.horizon_months]
    ]
    prior_total = float(sum(feature_values[:3]))
    recent_total = float(sum(feature_values[3:6]))
    future_total = float(sum(target_values))
    recent_status = "recently_inactive" if recent_total == 0 else "recently_scanning"
    future_over_recent = None if recent_total == 0 else future_total / recent_total
    feature_start_year, feature_start_month = _year_month_from_ordinal(int(window_ordinals[0]))
    feature_end_year, feature_end_month = _year_month_from_ordinal(int(window_ordinals[spec.feature_months - 1]))
    target_start_year, target_start_month = _year_month_from_ordinal(int(window_ordinals[spec.feature_months]))
    target_end_year, target_end_month = _year_month_from_ordinal(int(window_ordinals[-1]))
    feature_start = f"{feature_start_year:04d}-{feature_start_month:02d}-01"
    feature_end = f"{feature_end_year:04d}-{feature_end_month:02d}-01"
    target_start = f"{target_start_year:04d}-{target_start_month:02d}-01"
    target_end = f"{target_end_year:04d}-{target_end_month:02d}-01"
    row: dict[str, object] = {
        "influencer_id": influencer_id,
        "mobile_id": mobile_id,
        "state": state,
        "customer_name": customer_name,
        "feature_window_start_month": feature_start,
        "feature_window_end_month": feature_end,
        "target_window_start_month": target_start,
        "target_window_end_month": target_end,
        "feature_6m_total": sum(feature_values),
        "prior_3m_total": prior_total,
        "recent_3m_total": recent_total,
        "future_3m_total": future_total,
        "future_minus_recent": future_total - recent_total,
        "future_over_recent_ratio": future_over_recent,
        "zero_scans_last_3m_flag": recent_total == 0,
        "zero_scans_next_3m_flag": future_total == 0,
        "recent_status": recent_status,
        "recently_inactive": recent_status == "recently_inactive",
        "recently_scanning": recent_status == "recently_scanning",
        "feature_positive_month_count": sum(1 for value in feature_values if value > 0),
        "recent_positive_month_count": sum(1 for value in feature_values[3:6] if value > 0),
        "future_positive_month_count": sum(1 for value in target_values if value > 0),
        "future_any_scan_flag": future_total > 0,
        "feature_start_year": feature_start_year,
        "feature_end_year": feature_end_year,
        "target_start_year": target_start_year,
        "target_end_year": target_end_year,
        "cross_year_feature_flag": feature_start_year != feature_end_year,
        "cross_year_target_flag": target_start_year != target_end_year,
        "cross_year_6_plus_3_flag": feature_start_year != target_end_year,
    }
    for idx, value in enumerate(feature_values, start=1):
        row[f"feature_scan_m{idx}"] = value
    for idx, value in enumerate(target_values, start=1):
        row[f"future_scan_m{idx}"] = value
    return {column: row.get(column) for column in WINDOW_COLUMNS}


def _window_from_arrays(
    influencer_id: str,
    mobile_id: object,
    state: object,
    customer_name: object,
    periods: list[pd.Timestamp],
    scans: list[float],
    start: int,
    spec: WindowSpec,
) -> dict[str, object] | None:
    ordinals = pd.Series(periods).map(lambda value: value.year * 12 + value.month).to_numpy()
    return _window_from_ordinals(influencer_id, mobile_id, state, customer_name, ordinals, scans, start, spec)


def _legacy_window_row(window: dict[str, object]) -> dict[str, object]:
    row = {
        "mobile_id": window["mobile_id"],
        "State": window["state"],
        "Name": window["customer_name"],
        "MobileNo1": window["mobile_id"],
        "feature_start": pd.Timestamp(window["feature_window_start_month"]),
        "feature_end": pd.Timestamp(window["feature_window_end_month"]),
        "target_start": pd.Timestamp(window["target_window_start_month"]),
        "target_end": pd.Timestamp(window["target_window_end_month"]),
    }
    for idx in range(1, 7):
        row[f"scan_m{idx}"] = window[f"feature_scan_m{idx}"]
    for idx in range(1, 4):
        row[f"future_scan_m{idx}"] = window[f"future_scan_m{idx}"]
    return row


def _split_for_window(window: dict[str, object], holdout_year: int) -> str:
    target_start_year = int(window["target_start_year"])
    target_end_year = int(window["target_end_year"])
    if target_end_year <= holdout_year - 1:
        return "development"
    if target_start_year == holdout_year and target_end_year == holdout_year:
        return "holdout_2025"
    return "excluded_split_gap"


def _flush_window_batch(
    rows: list[dict[str, object]],
    output_path: Path,
    writer: pq.ParquetWriter | None,
) -> pq.ParquetWriter:
    frame = pd.DataFrame(rows, columns=WINDOW_COLUMNS)
    for column in [
        "feature_window_start_month",
        "feature_window_end_month",
        "target_window_start_month",
        "target_window_end_month",
    ]:
        frame[column] = pd.to_datetime(frame[column])
    table = pa.Table.from_pandas(frame, preserve_index=False)
    if writer is None:
        writer = pq.ParquetWriter(output_path, table.schema, compression="snappy")
    writer.write_table(table)
    return writer


def _update_split_stats(stats: WindowBuildStats, split: str, window: dict[str, object]) -> None:
    status = str(window["recent_status"])
    stats.split_recent_status_counts[(split, status)] += 1
    if window["zero_scans_last_3m_flag"]:
        stats.split_zero_last_counts[split] += 1
    if window["zero_scans_next_3m_flag"]:
        stats.split_zero_next_counts[split] += 1
    if window["cross_year_6_plus_3_flag"]:
        stats.split_cross_year_counts[split] += 1
    stats.split_recent_total_sum[split] += float(window["recent_3m_total"] or 0)
    stats.split_future_total_sum[split] += float(window["future_3m_total"] or 0)


def _update_example_counts(stats: WindowBuildStats, window: dict[str, object]) -> None:
    examples = {
        "2022-01_to_2022-06_target_2022-07_to_2022-09": (
            "2022-01-01",
            "2022-06-01",
            "2022-07-01",
            "2022-09-01",
        ),
        "2022-05_to_2022-10_target_2022-11_to_2023-01": (
            "2022-05-01",
            "2022-10-01",
            "2022-11-01",
            "2023-01-01",
        ),
        "2024-10_to_2025-03_target_2025-04_to_2025-06": (
            "2024-10-01",
            "2025-03-01",
            "2025-04-01",
            "2025-06-01",
        ),
    }
    actual = (
        str(window["feature_window_start_month"])[:10],
        str(window["feature_window_end_month"])[:10],
        str(window["target_window_start_month"])[:10],
        str(window["target_window_end_month"])[:10],
    )
    for name, expected in examples.items():
        if actual == expected:
            stats.example_counts[name] += 1


def _write_window_generation_summary(stats: WindowBuildStats, output_path: Path, holdout_year: int) -> None:
    rows = [
        {"metric": "influencers_seen", "value": stats.influencers_seen},
        {"metric": "influencers_with_windows", "value": stats.influencers_with_windows},
        {"metric": "total_candidate_windows", "value": stats.total_candidate_windows},
        {"metric": "generated_consecutive_windows", "value": stats.generated_windows},
        {"metric": "development_windows", "value": stats.development_windows},
        {"metric": "holdout_windows_2025", "value": stats.holdout_windows},
        {"metric": "excluded_split_gap_windows", "value": stats.excluded_split_windows},
        {"metric": "skipped_nonconsecutive_windows", "value": stats.skipped_nonconsecutive_windows},
    ]
    example_rows = [{"example_window": key, "count": value} for key, value in sorted(stats.example_counts.items())]
    split_rows = [
        {
            "split": split,
            "windows": count,
            "cross_year_6_plus_3_windows": stats.split_cross_year_counts[split],
            "zero_scans_last_3m_windows": stats.split_zero_last_counts[split],
            "zero_scans_next_3m_windows": stats.split_zero_next_counts[split],
        }
        for split, count in [
            ("development", stats.development_windows),
            ("holdout_2025", stats.holdout_windows),
        ]
    ]
    content = [
        "# Window Generation Summary",
        "## Split Rule",
        (
            f"- Development windows: full target horizon ends on or before {holdout_year - 1}-12.\n"
            f"- Holdout test windows: full target horizon starts in {holdout_year}-01 or later and ends by {holdout_year}-12.\n"
            "- Windows with target horizons crossing the development/holdout boundary are excluded to avoid leakage.\n"
            "- No churn label is created in this step."
        ),
        "## Counts",
        _markdown_table(rows),
        "## Split Diagnostics",
        _markdown_table(split_rows),
        "## Required Example Windows",
        _markdown_table(example_rows),
    ]
    output_path.write_text("\n\n".join(content) + "\n", encoding="utf-8")


def _write_recent_status_summary(stats: WindowBuildStats, output_path: Path) -> None:
    rows = []
    for split in ["development", "holdout_2025"]:
        split_total = stats.development_windows if split == "development" else stats.holdout_windows
        for status in ["recently_scanning", "recently_inactive"]:
            count = stats.split_recent_status_counts[(split, status)]
            rows.append(
                {
                    "split": split,
                    "recent_status": status,
                    "window_count": count,
                    "share_of_split": (count / split_total) if split_total else None,
                }
            )
    content = [
        "# Recent Status Summary",
        (
            "`recently_inactive` means the last three months of the six-month feature window sum to zero. "
            "`recently_scanning` means the last three months have some scans. This is a reporting segment, not a churn label."
        ),
        "## Counts by Split",
        _markdown_table(rows),
    ]
    output_path.write_text("\n\n".join(content) + "\n", encoding="utf-8")


def _markdown_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "_No rows._"
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_format_value(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _is_consecutive(periods: list[pd.Timestamp]) -> bool:
    if len(periods) < 2:
        return True
    normalized = pd.PeriodIndex(periods, freq="M")
    return all(current == previous + 1 for previous, current in zip(normalized[:-1], normalized[1:]))


def _normalize_panel_columns(panel: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    if "period" not in panel.columns and "month_date" in panel.columns:
        rename_map["month_date"] = "period"
    if "scan_value" not in panel.columns and "scan_points" in panel.columns:
        rename_map["scan_points"] = "scan_value"
    if "State" not in panel.columns and "original_state" in panel.columns:
        rename_map["original_state"] = "State"
    if "Name" not in panel.columns and "original_customer_name" in panel.columns:
        rename_map["original_customer_name"] = "Name"
    if "MobileNo1" not in panel.columns and "original_mobile_number" in panel.columns:
        rename_map["original_mobile_number"] = "MobileNo1"
    return panel.rename(columns=rename_map)


def _last_nonblank(values: Iterable[object]) -> object:
    result = None
    for value in values:
        if value is not None and str(value).strip() != "" and str(value).lower() != "nan":
            result = value
    return result


def _year_month_from_ordinal(ordinal: int) -> tuple[int, int]:
    year = (ordinal - 1) // 12
    month = ordinal - year * 12
    return year, month
