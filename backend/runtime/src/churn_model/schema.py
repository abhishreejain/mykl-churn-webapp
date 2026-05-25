"""Schema constants and lightweight validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd


MONTH_COLUMNS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
IDENTITY_COLUMNS = ["State", "Name", "MobileNo1"]
RAW_REQUIRED_COLUMNS = IDENTITY_COLUMNS + MONTH_COLUMNS
CANONICAL_RAW_COLUMNS = {
    "state": "State",
    "customer_name": "Name",
    "customer_mobile_number": "MobileNo1",
}

SCORING_IDENTIFIER_CANONICAL = {
    "state": "State",
    "customer_name": "Name",
    "customer_mobile_number": "MobileNo1",
}

SCORING_IDENTIFIER_ALIASES = {
    "State": ["State", "state", "State Name", "StateName"],
    "Name": ["Customer Name", "Customer name", "customer name", "Name", "customer_name"],
    "MobileNo1": [
        "Mobile no",
        "Mobile No",
        "mobile no",
        "mobileNo",
        "MobileNo",
        "MobileNo1",
        "Customer mobile number",
        "Customer Mobile Number",
        "mobile_no",
    ],
}

MONTH_NAME_TO_INDEX = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass(frozen=True)
class ColumnMapping:
    state: str = "State"
    customer_name: str = "Name"
    customer_mobile_number: str = "MobileNo1"
    months: tuple[str, ...] = tuple(MONTH_COLUMNS)


def infer_layout(columns: list[str]) -> str:
    normalized = {str(col).strip() for col in columns}
    if set(MONTH_COLUMNS).issubset(normalized):
        return "Jan-Dec wide"
    if {"month", "date", "period"}.intersection({c.lower() for c in normalized}):
        return "monthly-long candidate"
    return "unknown/other"


def normalize_column_token(value: object) -> str:
    return "".join(ch for ch in str(value).strip().lower() if ch.isalnum())


def build_alias_lookup(alias_config: dict[str, list[str]] | None) -> dict[str, str]:
    defaults = {
        "state": ["State", "state", "State Name", "StateName"],
        "customer_name": ["Name", "Customer name", "Customer Name", "customer name", "Influencer Name"],
        "customer_mobile_number": [
            "MobileNo1",
            "MobileNo",
            "mobileNo",
            "Mobile No",
            "Mobile no",
            "mobile no",
            "Mobile No.",
            "Mobile",
            "Customer mobile number",
            "Customer Mobile Number",
            "Phone",
            "Contact",
        ],
    }
    merged = defaults | (alias_config or {})
    lookup: dict[str, str] = {}
    for canonical, aliases in merged.items():
        target = CANONICAL_RAW_COLUMNS.get(canonical, canonical)
        for alias in aliases:
            lookup[normalize_column_token(alias)] = target
    for month in MONTH_COLUMNS:
        lookup[normalize_column_token(month)] = month
    return lookup


def apply_column_aliases(df: pd.DataFrame, alias_config: dict[str, list[str]] | None = None) -> pd.DataFrame:
    lookup = build_alias_lookup(alias_config)
    rename: dict[object, str] = {}
    seen: set[str] = set()
    for column in df.columns:
        stripped = str(column).strip()
        canonical = lookup.get(normalize_column_token(stripped), stripped)
        if canonical in seen:
            canonical = stripped
        seen.add(canonical)
        rename[column] = canonical
    return df.rename(columns=rename)


def missing_required_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in RAW_REQUIRED_COLUMNS if col not in df.columns]


def validate_raw_wide_schema(df: pd.DataFrame, source: str) -> None:
    missing = missing_required_columns(df)
    if missing:
        raise ValueError(f"{source} is missing required columns: {missing}")


def canonicalize_scoring_identifier_columns(
    df: pd.DataFrame,
    state_column: str | None = None,
    name_column: str | None = None,
    mobile_column: str | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rename scoring identifier columns to canonical names.

    Canonical names:
    - `State`
    - `Name`
    - `MobileNo1`
    """
    columns = [str(c) for c in df.columns]
    column_set = set(columns)
    explicit = {
        "State": state_column,
        "Name": name_column,
        "MobileNo1": mobile_column,
    }
    rename: dict[str, str] = {}
    resolved: dict[str, str] = {}

    for canonical, override in explicit.items():
        if override:
            if override not in column_set:
                raise ValueError(f"Configured identifier column `{override}` not found for `{canonical}`.")
            resolved[canonical] = override

    alias_lookup = {
        canonical: {normalize_column_token(alias) for alias in aliases}
        for canonical, aliases in SCORING_IDENTIFIER_ALIASES.items()
    }
    normalized_to_cols: dict[str, list[str]] = {}
    for col in columns:
        normalized_to_cols.setdefault(normalize_column_token(col), []).append(col)

    for canonical in ["State", "Name", "MobileNo1"]:
        if canonical in resolved:
            continue
        matches: list[str] = []
        for token in alias_lookup[canonical]:
            matches.extend(normalized_to_cols.get(token, []))
        matches = sorted(set(matches))
        if not matches:
            raise ValueError(
                f"Missing required identifier column for `{canonical}`. "
                f"Accepted aliases: {SCORING_IDENTIFIER_ALIASES[canonical]}"
            )
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous identifier mapping for `{canonical}`. Candidate columns: {matches}. "
                "Use explicit override arguments to choose one."
            )
        resolved[canonical] = matches[0]

    if len(set(resolved.values())) != 3:
        raise ValueError(
            "Identifier column mapping is not one-to-one. "
            f"Resolved mappings: {resolved}"
        )

    for canonical, original in resolved.items():
        if original != canonical:
            rename[original] = canonical
    return df.rename(columns=rename), resolved


def detect_scoring_scan_columns(
    df: pd.DataFrame,
    identifier_columns: tuple[str, str, str] = ("State", "Name", "MobileNo1"),
    manual_scan_columns: list[str] | None = None,
) -> list[str]:
    """Detect six scoring scan columns and preserve left-to-right file order.

    If `manual_scan_columns` is provided, it must contain exactly six existing columns.
    Otherwise, inference uses all non-identifier columns and requires exactly six columns.
    Header names are accepted as-is in file order. Extra validation is applied when the
    six headers are clearly generic `Month N scan` or month-name labels.
    """
    columns = [str(c) for c in df.columns]
    missing_ids = [col for col in identifier_columns if col not in columns]
    if missing_ids:
        raise ValueError(f"Missing required identifier columns after canonicalization: {missing_ids}")

    if manual_scan_columns is not None:
        cleaned = [str(c).strip() for c in manual_scan_columns if str(c).strip()]
        if len(cleaned) != 6:
            raise ValueError(
                f"Manual --scan-columns must provide exactly 6 columns, got {len(cleaned)}: {cleaned}"
            )
        missing = [col for col in cleaned if col not in columns]
        if missing:
            raise ValueError(f"Manual scan columns not found in input file: {missing}")
        return cleaned

    candidate_scan_columns = [c for c in columns if c not in set(identifier_columns)]
    if len(candidate_scan_columns) != 6:
        raise ValueError(
            "Automatic scan-column inference requires exactly 6 non-identifier columns. "
            f"Found {len(candidate_scan_columns)}: {candidate_scan_columns}"
        )

    generic_numbers = [_generic_month_number(c) for c in candidate_scan_columns]
    if all(number is not None for number in generic_numbers):
        sequence = [int(number) for number in generic_numbers]
        if sequence != [1, 2, 3, 4, 5, 6]:
            raise ValueError(
                "Generic scan headers must appear left-to-right as Month 1 scan ... Month 6 scan. "
                f"Detected order: {sequence} from columns {candidate_scan_columns}"
            )
        return candidate_scan_columns

    month_indices = [_month_name_index(c) for c in candidate_scan_columns]
    if all(index is not None for index in month_indices):
        concrete_month_indices = [int(index) for index in month_indices]
        for idx in range(1, len(concrete_month_indices)):
            expected = (concrete_month_indices[idx - 1] % 12) + 1
            if concrete_month_indices[idx] != expected:
                raise ValueError(
                    "Month-name scan headers must be six consecutive months in left-to-right order. "
                    f"Detected month indices: {concrete_month_indices} from columns {candidate_scan_columns}"
                )
    return candidate_scan_columns


def _scan_header_style(column_name: str) -> str:
    if _generic_month_number(column_name) is not None:
        return "generic"
    if _month_name_index(column_name) is not None:
        return "month_name"
    return "unknown"


def _generic_month_number(column_name: str) -> int | None:
    text = str(column_name).strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "", text)
    # Supports "Month 1 scan", "month1scan", "month-1-scan"
    match = re.fullmatch(r"month([1-6])scan", normalized)
    if not match:
        return None
    return int(match.group(1))


def _month_name_index(column_name: str) -> int | None:
    text = str(column_name).strip().lower()
    token = normalize_column_token(text)
    if token in MONTH_NAME_TO_INDEX:
        return MONTH_NAME_TO_INDEX[token]

    match = re.search(
        r"(?<![a-z])(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])",
        text,
    )
    if not match:
        return None
    return MONTH_NAME_TO_INDEX.get(normalize_column_token(match.group(1)))
