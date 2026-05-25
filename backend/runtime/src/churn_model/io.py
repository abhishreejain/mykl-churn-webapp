"""Input/output helpers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from churn_model.schema import infer_layout

LOGGER = logging.getLogger(__name__)


SUPPORTED_RAW_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def infer_year_from_path(path: str | Path) -> int | None:
    matches = re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(path))
    if not matches:
        return None
    unique = sorted(set(int(match) for match in matches))
    return unique[0] if len(unique) == 1 else None


def discover_raw_files(raw_dir: str | Path) -> list[Path]:
    raw_path = Path(raw_dir)
    files = [
        path
        for path in raw_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_RAW_EXTENSIONS
    ]
    return sorted(files)


def read_excel_sheets(path: str | Path) -> dict[str, pd.DataFrame]:
    workbook = pd.ExcelFile(path)
    return {sheet: workbook.parse(sheet) for sheet in workbook.sheet_names}


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def read_scoring_input(path: str | Path) -> pd.DataFrame:
    """Read a scoring input file from CSV/XLS/XLSX with encoding fallback for CSV."""
    input_path = Path(path)
    if input_path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)

    csv_read_errors: list[str] = []
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(input_path, encoding=encoding)
        except UnicodeDecodeError as exc:
            csv_read_errors.append(f"{encoding}: {exc}")
    raise UnicodeDecodeError(
        "utf-8",
        b"",
        0,
        1,
        "Unable to decode scoring CSV with supported encodings "
        f"(utf-8, utf-8-sig, cp1252, latin1). Errors: {csv_read_errors}",
    )


def write_csv(df: pd.DataFrame, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    LOGGER.info("Wrote %s rows to %s", len(df), output)
    return output


def dataframe_summary(df: pd.DataFrame) -> dict[str, object]:
    columns = [str(col) for col in df.columns]
    return {
        "row_count": int(len(df)),
        "column_count": int(len(columns)),
        "column_names": "|".join(columns),
        "layout_classification": infer_layout(columns),
    }


def concatenate_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    materialized = list(frames)
    if not materialized:
        return pd.DataFrame()
    return pd.concat(materialized, ignore_index=True)
