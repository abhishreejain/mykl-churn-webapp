"""Continuous monthly panel construction."""

from __future__ import annotations

import calendar
import csv
import heapq
import logging
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from churn_model.schema import MONTH_COLUMNS
from churn_model.yearly_builder import load_yearly_files

LOGGER = logging.getLogger(__name__)

PANEL_COLUMNS = [
    "influencer_id",
    "mobile_id",
    "mobile_is_valid",
    "mobile_cleaning_issue",
    "original_state",
    "original_customer_name",
    "original_mobile_number",
    "month_date",
    "calendar_year",
    "calendar_month",
    "month_name",
    "scan_points",
    "source_year",
    "source_file",
    "source_sheet",
    "source_row_number",
    "duplicate_resolution_rule",
    "source_duplicate_row_count",
]

COVERAGE_COLUMNS = [
    "influencer_id",
    "mobile_id",
    "mobile_is_valid",
    "first_month",
    "last_month",
    "observed_month_count",
    "expected_month_count",
    "missing_month_count",
    "continuity_gap_count",
    "years_covered",
    "year_count",
    "has_cross_year_coverage",
    "total_scan_points",
    "positive_scan_month_count",
    "source_duplicate_row_count_max",
]


@dataclass
class PanelBuildStats:
    panel_rows: int = 0
    influencer_count: int = 0
    influencers_with_missing_months: int = 0
    total_missing_months: int = 0
    max_missing_months: int = 0
    max_continuity_gaps: int = 0
    month_year_counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    month_year_influencers: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    source_year_influencers: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    source_year_rows: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    cross_year_eligible: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cross_year_continuous: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cross_year_breaks: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def build_monthly_panel_from_yearly(yearly_df: pd.DataFrame) -> pd.DataFrame:
    """In-memory helper retained for tests and small datasets."""
    work = yearly_df.copy()
    work["influencer_id"] = work.apply(_influencer_id_from_row, axis=1)
    id_columns = [
        "influencer_id",
        "mobile_id",
        "mobile_is_valid",
        "mobile_cleaning_issue",
        "State",
        "Name",
        "MobileNo1",
        "source_year",
        "source_file",
        "source_sheet",
        "source_row_number",
        "duplicate_resolution_rule",
        "source_duplicate_row_count",
    ]
    panel = work.melt(id_vars=id_columns, value_vars=MONTH_COLUMNS, var_name="month_name", value_name="scan_points")
    month_lookup = {month: index for index, month in enumerate(calendar.month_abbr) if month}
    panel["calendar_month"] = panel["month_name"].map(month_lookup).astype("int64")
    panel["calendar_year"] = panel["source_year"].astype("int64")
    panel["month_date"] = pd.to_datetime(
        {"year": panel["calendar_year"], "month": panel["calendar_month"], "day": 1}
    )
    panel = panel.rename(
        columns={
            "State": "original_state",
            "Name": "original_customer_name",
            "MobileNo1": "original_mobile_number",
        }
    )
    return panel[PANEL_COLUMNS].sort_values(["influencer_id", "month_date"]).reset_index(drop=True)


def build_monthly_panel(processed_dir: Path, output_path: Path, reports_dir: Path | None = None) -> Path:
    """Build a parquet monthly panel and coverage reports from cleaned yearly wide CSVs."""
    reports_dir = reports_dir or output_path.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path = reports_dir / "monthly_coverage_by_influencer.csv"
    summary_path = reports_dir / "monthly_panel_summary.md"

    yearly_files = sorted(processed_dir.glob("yearly_*_cleaned.csv"))
    if not yearly_files:
        # Backward-compatible fallback for tests/small ad hoc runs.
        yearly_df = load_yearly_files(processed_dir)
        panel = build_monthly_panel_from_yearly(yearly_df)
        panel.to_parquet(output_path, index=False)
        coverage = build_coverage_frame(panel)
        coverage.to_csv(coverage_path, index=False)
        write_monthly_panel_summary(panel, coverage, summary_path)
        return output_path

    with tempfile.TemporaryDirectory(prefix="panel_sort_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        sorted_files = [_write_sorted_year_file(path, temp_dir) for path in yearly_files]
        stats = PanelBuildStats()
        _write_panel_and_coverage(sorted_files, output_path, coverage_path, stats)

    write_summary_from_stats(stats, summary_path)
    LOGGER.info("Wrote monthly panel parquet to %s", output_path)
    LOGGER.info("Wrote monthly coverage report to %s", coverage_path)
    LOGGER.info("Wrote monthly panel summary to %s", summary_path)
    return output_path


def load_monthly_panel(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, parse_dates=["month_date"])


def build_coverage_frame(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for influencer_id, group in panel.groupby("influencer_id", dropna=False):
        ordinals = sorted(_month_ordinal(pd.Timestamp(value).year, pd.Timestamp(value).month) for value in group["month_date"])
        rows.append(_coverage_row_from_ordinals(str(influencer_id), group.iloc[0], ordinals, group))
    return pd.DataFrame(rows, columns=COVERAGE_COLUMNS)


def write_monthly_panel_summary(panel: pd.DataFrame, coverage: pd.DataFrame, output_path: Path) -> None:
    month_coverage = (
        panel.groupby("calendar_year")
        .agg(
            panel_rows=("influencer_id", "size"),
            unique_influencers=("influencer_id", "nunique"),
            months_present=("calendar_month", "nunique"),
            min_month=("month_date", "min"),
            max_month=("month_date", "max"),
        )
        .reset_index()
    )
    sections = [
        "## Month Coverage by Year\n\n" + month_coverage.to_markdown(index=False),
        "## Timeline Continuity Diagnostics\n\n"
        + f"- Total influencers: {len(coverage):,}\n"
        + f"- Influencers with missing months between first and last observed month: {(coverage['missing_month_count'] > 0).sum():,}\n"
        + f"- Total missing months between first and last observed month: {int(coverage['missing_month_count'].sum()):,}",
    ]
    output_path.write_text("# Monthly Panel Summary\n\n" + "\n\n".join(sections) + "\n", encoding="utf-8")


def _write_sorted_year_file(path: Path, temp_dir: Path, chunk_size: int = 100_000) -> Path:
    LOGGER.info("Sorting cleaned yearly file by influencer timeline key: %s", path)
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, chunksize=chunk_size):
        chunk["influencer_id"] = chunk.apply(_influencer_id_from_row, axis=1)
        chunks.append(chunk)
    data = pd.concat(chunks, ignore_index=True)
    data = data.sort_values(["influencer_id", "source_year", "source_row_number"], kind="mergesort")
    output = temp_dir / f"{path.stem}_sorted.csv"
    data.to_csv(output, index=False)
    return output


def _write_panel_and_coverage(
    sorted_files: list[Path],
    panel_path: Path,
    coverage_path: Path,
    stats: PanelBuildStats,
    batch_size: int = 250_000,
) -> None:
    readers = [_CsvRowStream(path) for path in sorted_files]
    heap: list[tuple[str, int, dict[str, str]]] = []
    for index, reader in enumerate(readers):
        row = reader.next_row()
        if row is not None:
            heapq.heappush(heap, (row["influencer_id"], index, row))

    writer: pq.ParquetWriter | None = None
    panel_batch: list[dict[str, object]] = []
    with coverage_path.open("w", encoding="utf-8", newline="") as coverage_handle:
        coverage_writer = csv.DictWriter(coverage_handle, fieldnames=COVERAGE_COLUMNS)
        coverage_writer.writeheader()
        while heap:
            influencer_id = heap[0][0]
            grouped_rows: list[dict[str, str]] = []
            while heap and heap[0][0] == influencer_id:
                _, reader_index, row = heapq.heappop(heap)
                grouped_rows.append(row)
                next_row = readers[reader_index].next_row()
                if next_row is not None:
                    heapq.heappush(heap, (next_row["influencer_id"], reader_index, next_row))

            panel_rows = _monthly_rows_for_influencer(influencer_id, grouped_rows)
            panel_rows.sort(key=lambda item: item["month_date"])
            panel_batch.extend(panel_rows)
            _update_stats(stats, influencer_id, grouped_rows, panel_rows)
            coverage_writer.writerow(_coverage_row(influencer_id, grouped_rows, panel_rows))

            if len(panel_batch) >= batch_size:
                writer = _flush_panel_batch(panel_batch, panel_path, writer)
                panel_batch = []

    if panel_batch:
        writer = _flush_panel_batch(panel_batch, panel_path, writer)
    if writer is not None:
        writer.close()
    for reader in readers:
        reader.close()


def _monthly_rows_for_influencer(influencer_id: str, yearly_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in yearly_rows:
        source_year = int(float(row["source_year"]))
        for month_number, month_name in enumerate(MONTH_COLUMNS, start=1):
            rows.append(
                {
                    "influencer_id": influencer_id,
                    "mobile_id": _none_if_blank(row.get("mobile_id")),
                    "mobile_is_valid": _to_bool(row.get("mobile_is_valid")),
                    "mobile_cleaning_issue": _none_if_blank(row.get("mobile_cleaning_issue")),
                    "original_state": _none_if_blank(row.get("State")),
                    "original_customer_name": _none_if_blank(row.get("Name")),
                    "original_mobile_number": _none_if_blank(row.get("MobileNo1")),
                    "month_date": f"{source_year:04d}-{month_number:02d}-01",
                    "calendar_year": source_year,
                    "calendar_month": month_number,
                    "month_name": month_name,
                    "scan_points": _to_float(row.get(month_name)),
                    "source_year": source_year,
                    "source_file": _none_if_blank(row.get("source_file")),
                    "source_sheet": _none_if_blank(row.get("source_sheet")),
                    "source_row_number": _to_int(row.get("source_row_number")),
                    "duplicate_resolution_rule": _none_if_blank(row.get("duplicate_resolution_rule")),
                    "source_duplicate_row_count": _to_int(row.get("source_duplicate_row_count")),
                }
            )
    return rows


def _flush_panel_batch(
    rows: list[dict[str, object]],
    panel_path: Path,
    writer: pq.ParquetWriter | None,
) -> pq.ParquetWriter:
    frame = pd.DataFrame(rows, columns=PANEL_COLUMNS)
    frame["month_date"] = pd.to_datetime(frame["month_date"])
    table = pa.Table.from_pandas(frame, preserve_index=False)
    if writer is None:
        writer = pq.ParquetWriter(panel_path, table.schema, compression="snappy")
    writer.write_table(table)
    return writer


def _coverage_row(influencer_id: str, yearly_rows: list[dict[str, str]], panel_rows: list[dict[str, object]]) -> dict[str, object]:
    ordinals = sorted(_month_ordinal(int(row["calendar_year"]), int(row["calendar_month"])) for row in panel_rows)
    first = panel_rows[0]
    total_scan = sum(float(row["scan_points"] or 0) for row in panel_rows)
    positive_count = sum(1 for row in panel_rows if float(row["scan_points"] or 0) > 0)
    max_dup = max(_to_int(row.get("source_duplicate_row_count")) or 0 for row in yearly_rows)
    return _coverage_row_from_ordinals(
        influencer_id=influencer_id,
        first_row=pd.Series(first),
        ordinals=ordinals,
        panel_group=pd.DataFrame({"scan_points": [total_scan], "positive_count": [positive_count], "max_dup": [max_dup]}),
    )


def _coverage_row_from_ordinals(
    influencer_id: str,
    first_row: pd.Series,
    ordinals: list[int],
    panel_group: pd.DataFrame,
) -> dict[str, object]:
    unique_ordinals = sorted(set(ordinals))
    first_ordinal = unique_ordinals[0]
    last_ordinal = unique_ordinals[-1]
    expected = last_ordinal - first_ordinal + 1
    missing = expected - len(unique_ordinals)
    continuity_gaps = sum(
        max(0, current - previous - 1) for previous, current in zip(unique_ordinals[:-1], unique_ordinals[1:])
    )
    years = sorted({_year_from_ordinal(value) for value in unique_ordinals})
    total_scan = (
        float(panel_group["scan_points"].sum())
        if "positive_count" not in panel_group.columns
        else float(panel_group["scan_points"].iloc[0])
    )
    positive_count = (
        int((panel_group["scan_points"] > 0).sum())
        if "positive_count" not in panel_group.columns
        else int(panel_group["positive_count"].iloc[0])
    )
    max_dup = (
        int(panel_group["source_duplicate_row_count"].max())
        if "source_duplicate_row_count" in panel_group.columns
        else int(panel_group["max_dup"].iloc[0])
    )
    return {
        "influencer_id": influencer_id,
        "mobile_id": first_row.get("mobile_id"),
        "mobile_is_valid": first_row.get("mobile_is_valid"),
        "first_month": _date_from_ordinal(first_ordinal),
        "last_month": _date_from_ordinal(last_ordinal),
        "observed_month_count": len(unique_ordinals),
        "expected_month_count": expected,
        "missing_month_count": missing,
        "continuity_gap_count": continuity_gaps,
        "years_covered": "|".join(str(year) for year in years),
        "year_count": len(years),
        "has_cross_year_coverage": len(years) > 1,
        "total_scan_points": total_scan,
        "positive_scan_month_count": positive_count,
        "source_duplicate_row_count_max": max_dup,
    }


def _update_stats(
    stats: PanelBuildStats,
    influencer_id: str,
    yearly_rows: list[dict[str, str]],
    panel_rows: list[dict[str, object]],
) -> None:
    stats.influencer_count += 1
    stats.panel_rows += len(panel_rows)
    ordinals = sorted({_month_ordinal(int(row["calendar_year"]), int(row["calendar_month"])) for row in panel_rows})
    missing = (ordinals[-1] - ordinals[0] + 1) - len(ordinals)
    gaps = sum(max(0, current - previous - 1) for previous, current in zip(ordinals[:-1], ordinals[1:]))
    if missing:
        stats.influencers_with_missing_months += 1
        stats.total_missing_months += missing
        stats.max_missing_months = max(stats.max_missing_months, missing)
        stats.max_continuity_gaps = max(stats.max_continuity_gaps, gaps)

    years_present = sorted({_year_from_ordinal(value) for value in ordinals})
    for row in panel_rows:
        year = int(row["calendar_year"])
        stats.month_year_counts[year] += 1
        stats.month_year_influencers[year].add(influencer_id)
    for row in yearly_rows:
        source_year = int(float(row["source_year"]))
        stats.source_year_rows[source_year] += 1
        stats.source_year_influencers[source_year].add(influencer_id)
    for year in years_present:
        if year + 1 in years_present:
            key = f"{year}-{year + 1}"
            stats.cross_year_eligible[key] += 1
            dec = _month_ordinal(year, 12)
            jan = _month_ordinal(year + 1, 1)
            if dec in ordinals and jan in ordinals:
                stats.cross_year_continuous[key] += 1
            else:
                stats.cross_year_breaks[key] += 1


def write_summary_from_stats(stats: PanelBuildStats, output_path: Path) -> None:
    month_rows = []
    for year in sorted(stats.month_year_counts):
        month_rows.append(
            {
                "year": year,
                "panel_rows": stats.month_year_counts[year],
                "unique_influencers": len(stats.month_year_influencers[year]),
                "months_present": 12,
                "min_month": f"{year}-01-01",
                "max_month": f"{year}-12-01",
            }
        )
    source_rows = []
    for year in sorted(stats.source_year_influencers):
        source_rows.append(
            {
                "source_year": year,
                "cleaned_year_rows": stats.source_year_rows[year],
                "unique_influencers": len(stats.source_year_influencers[year]),
            }
        )
    cross_rows = []
    for key in sorted(stats.cross_year_eligible):
        cross_rows.append(
            {
                "year_pair": key,
                "influencers_present_in_both_years": stats.cross_year_eligible[key],
                "continuous_dec_to_jan": stats.cross_year_continuous[key],
                "breaks": stats.cross_year_breaks[key],
            }
        )

    sections = [
        "## Month Coverage by Year\n\n" + _markdown_table(month_rows),
        "## Influencer Counts by Year\n\n" + _markdown_table(source_rows),
        "## Timeline Continuity Diagnostics\n\n"
        + f"- Total influencers: {stats.influencer_count:,}\n"
        + f"- Total monthly panel rows: {stats.panel_rows:,}\n"
        + f"- Influencers with missing months between first and last observed month: {stats.influencers_with_missing_months:,}\n"
        + f"- Total missing months between first and last observed month: {stats.total_missing_months:,}\n"
        + f"- Maximum missing months for one influencer: {stats.max_missing_months:,}\n"
        + f"- Maximum continuity gap count for one influencer: {stats.max_continuity_gaps:,}",
        "## Missing-Month Diagnostics\n\n"
        + "Missing months are counted between each influencer's first and last observed source month. "
        + "They are diagnostics only and do not define churn, activity, or inactivity.",
        "## Cross-Year Continuity Checks\n\n" + _markdown_table(cross_rows),
    ]
    output_path.write_text("# Monthly Panel Summary\n\n" + "\n\n".join(sections) + "\n", encoding="utf-8")


def _markdown_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "_No rows._"
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


class _CsvRowStream:
    def __init__(self, path: Path) -> None:
        self.handle = path.open("r", encoding="utf-8", newline="")
        self.reader = csv.DictReader(self.handle)

    def next_row(self) -> dict[str, str] | None:
        try:
            return next(self.reader)
        except StopIteration:
            return None

    def close(self) -> None:
        self.handle.close()


def _influencer_id_from_row(row: pd.Series) -> str:
    mobile_id = row.get("mobile_id")
    mobile_is_valid = row.get("mobile_is_valid", True)
    if pd.notna(mobile_id) and str(mobile_id).strip() and _to_bool(mobile_is_valid):
        return str(mobile_id).strip()
    return f"INVALID::{row.get('source_year')}::{row.get('source_file')}::{row.get('source_sheet')}::{row.get('source_row_number')}"


def _month_ordinal(year: int, month: int) -> int:
    return year * 12 + month


def _year_from_ordinal(ordinal: int) -> int:
    return (ordinal - 1) // 12


def _date_from_ordinal(ordinal: int) -> str:
    year = _year_from_ordinal(ordinal)
    month = ordinal - year * 12
    return f"{year:04d}-{month:02d}-01"


def _none_if_blank(value: object) -> object | None:
    if value is None:
        return None
    text = str(value)
    return None if text == "" or text.lower() == "nan" else value


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _to_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _to_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(value))
