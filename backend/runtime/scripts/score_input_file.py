"""Score a production input file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from churn_model.logging_utils import setup_logging
from churn_model.web_runtime import ScoringJobRequest, run_scoring_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-config",
        default="artifacts/production/config_used.yaml",
        help="Optional production runtime config artifact used for runtime defaults.",
    )
    parser.add_argument(
        "--metadata",
        default="artifacts/production/metadata.json",
        help="Optional production metadata artifact used for runtime defaults.",
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--scan-columns",
        default=None,
        help=(
            "Optional manual override: comma-separated list of 6 scan columns in oldest->newest order "
            "(e.g. Oct,Nov,Dec,Jan,Feb,Mar)."
        ),
    )
    parser.add_argument(
        "--state-column",
        default=None,
        help="Optional explicit source column name for State when alias auto-detection is ambiguous.",
    )
    parser.add_argument(
        "--name-column",
        default=None,
        help="Optional explicit source column name for Customer name when alias auto-detection is ambiguous.",
    )
    parser.add_argument(
        "--mobile-column",
        default=None,
        help="Optional explicit source column name for mobile number when alias auto-detection is ambiguous.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def _resolve_default_output_path(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)
    input_path = Path(args.input)
    return input_path.with_name(f"{input_path.stem}_scored.csv")


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    scan_columns = [part.strip() for part in args.scan_columns.split(",")] if args.scan_columns else None
    request = ScoringJobRequest(
        input_path=Path(args.input),
        output_path=_resolve_default_output_path(args),
        model_path=Path(args.model) if args.model else None,
        runtime_config_path=Path(args.runtime_config),
        metadata_path=Path(args.metadata),
        manual_scan_columns=scan_columns,
        state_column=args.state_column,
        name_column=args.name_column,
        mobile_column=args.mobile_column,
        project_root=Path(".").resolve(),
    )
    run_scoring_job(
        request=request,
        raise_on_error=True,
    )


if __name__ == "__main__":
    main()
