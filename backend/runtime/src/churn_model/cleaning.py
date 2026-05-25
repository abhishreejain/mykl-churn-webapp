"""Data cleaning utilities."""

from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

from churn_model.schema import MONTH_COLUMNS


@dataclass(frozen=True)
class MobileCleanResult:
    mobile_id: str | None
    digits: str | None
    is_valid: bool
    issue: str


def blank_mask(series: pd.Series, blank_tokens: list[str]) -> pd.Series:
    tokens = {str(token).strip().lower() for token in blank_tokens}
    as_text = series.astype("string").str.strip().str.lower()
    return series.isna() | as_text.isin(tokens)


def normalize_mobile(value: object, prefer_last_n_digits: int = 10, valid_lengths: tuple[int, ...] = (10,)) -> str | None:
    return clean_mobile(value, prefer_last_n_digits, valid_lengths).mobile_id


def clean_mobile(
    value: object,
    prefer_last_n_digits: int = 10,
    valid_lengths: tuple[int, ...] = (10,),
) -> MobileCleanResult:
    if pd.isna(value):
        return MobileCleanResult(None, None, False, "blank")
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    if not digits:
        return MobileCleanResult(None, None, False, "no_digits")
    if len(digits) in valid_lengths:
        return MobileCleanResult(digits, digits, True, "valid")
    if prefer_last_n_digits and len(digits) > prefer_last_n_digits:
        canonical = digits[-prefer_last_n_digits:]
        if len(canonical) in valid_lengths:
            return MobileCleanResult(canonical, digits, True, f"trimmed_to_last_{prefer_last_n_digits}")
    return MobileCleanResult(digits, digits, False, f"invalid_length_{len(digits)}")


def clean_scan_value(value: object) -> float:
    if pd.isna(value) or value == "":
        return np.nan
    return float(value)


def standardize_state(value: object) -> str | pd.NA:
    if pd.isna(value):
        return pd.NA
    text = re.sub(r"\s+", " ", str(value).strip())
    return text.upper() if text else pd.NA


def standardize_name(value: object) -> str | pd.NA:
    if pd.isna(value):
        return pd.NA
    text = re.sub(r"\s+", " ", str(value).strip())
    return text if text else pd.NA


def standardize_raw_wide(
    df: pd.DataFrame,
    year: int,
    source_file: str,
    sheet_name: str,
    blank_tokens: list[str] | None = None,
    prefer_last_n_digits: int = 10,
    valid_mobile_lengths: tuple[int, ...] = (10,),
) -> tuple[pd.DataFrame, dict[str, object]]:
    cleaned = df.copy()
    cleaned.columns = [str(col).strip() for col in cleaned.columns]
    blank_tokens = blank_tokens or ["", " ", "-", "--", "NA", "N/A", "NULL", "null", "None"]
    report: dict[str, object] = {
        "source_file": source_file,
        "source_sheet": sheet_name,
        "source_year": int(year),
        "input_rows": int(len(cleaned)),
    }

    for column in ["State", "Name", "MobileNo1", *MONTH_COLUMNS]:
        mask = blank_mask(cleaned[column], blank_tokens)
        report[f"{column}_blank_or_null_count"] = int(mask.sum())
        cleaned.loc[mask, column] = pd.NA

    cleaned["source_year"] = int(year)
    cleaned["source_file"] = source_file
    cleaned["source_sheet"] = sheet_name
    cleaned["source_row_number"] = np.arange(2, len(cleaned) + 2)
    mobile_results = cleaned["MobileNo1"].map(
        lambda value: clean_mobile(value, prefer_last_n_digits, valid_mobile_lengths)
    )
    cleaned["mobile_digits"] = mobile_results.map(lambda item: item.digits)
    cleaned["mobile_id"] = mobile_results.map(lambda item: item.mobile_id)
    cleaned["mobile_is_valid"] = mobile_results.map(lambda item: item.is_valid)
    cleaned["mobile_cleaning_issue"] = mobile_results.map(lambda item: item.issue)
    cleaned["State"] = cleaned["State"].map(standardize_state).astype("string")
    cleaned["Name"] = cleaned["Name"].map(standardize_name).astype("string")
    for month in MONTH_COLUMNS:
        nonblank_before = cleaned[month].notna()
        cleaned[month] = pd.to_numeric(cleaned[month], errors="coerce")
        report[f"{month}_numeric_coerce_to_null_count"] = int((nonblank_before & cleaned[month].isna()).sum())
    report["invalid_mobile_count"] = int((~cleaned["mobile_is_valid"]).sum())
    report["trimmed_mobile_count"] = int((cleaned["mobile_cleaning_issue"].str.startswith("trimmed")).sum())
    return cleaned, report


def add_recent_status(df: pd.DataFrame, scan_columns: list[str]) -> pd.DataFrame:
    if len(scan_columns) != 6:
        raise ValueError("recent status requires exactly six scan columns")
    result = df.copy()
    last_three = scan_columns[-3:]
    recent_sum = result[last_three].fillna(0).sum(axis=1)
    result["recent_status"] = np.where(recent_sum > 0, "recently_scanning", "recently_inactive")
    return result


def find_duplicate_mobile_scan_conflicts(
    df: pd.DataFrame,
    mobile_column: str,
    scan_columns: list[str],
) -> list[dict[str, object]]:
    """Return duplicate-mobile groups that contain conflicting scan values."""
    if len(scan_columns) != 6:
        raise ValueError("duplicate scan conflict check requires exactly six scan columns")
    missing = [column for column in [mobile_column, *scan_columns] if column not in df.columns]
    if missing:
        raise ValueError(f"duplicate scan conflict check missing columns: {missing}")

    duplicates = df[df[mobile_column].notna()].copy()
    duplicates = duplicates[duplicates[mobile_column].duplicated(keep=False)].copy()
    if duplicates.empty:
        return []

    scan_view = duplicates[[mobile_column, *scan_columns]].copy()
    scan_view[scan_columns] = scan_view[scan_columns].apply(pd.to_numeric, errors="coerce")

    def _signature(row: pd.Series) -> tuple[object, ...]:
        signature: list[object] = []
        for value in row.tolist():
            if pd.isna(value):
                signature.append("NA")
            else:
                signature.append(float(value))
        return tuple(signature)

    scan_view["__scan_signature"] = scan_view[scan_columns].apply(_signature, axis=1)
    conflicts: list[dict[str, object]] = []
    for mobile_id, group in scan_view.groupby(mobile_column, dropna=False):
        unique_signatures = group["__scan_signature"].drop_duplicates().tolist()
        if len(unique_signatures) <= 1:
            continue
        conflicts.append(
            {
                "mobile_id": mobile_id,
                "row_count": int(len(group)),
                "unique_scan_patterns": int(len(unique_signatures)),
                "sample_scan_patterns": unique_signatures[:3],
            }
        )
    return conflicts
