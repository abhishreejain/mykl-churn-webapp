"""Append Potential and Potential Band to a scored output file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from churn_model.logging_utils import setup_logging
from churn_model.potential_enrichment import POTENTIAL_LOOKUP_FILENAME
from churn_model.web_runtime import PotentialJobRequest, run_potential_enrichment_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help=(
            "Scored input file with exact schema/order: "
            "State, Customer name, Customer mobile number, Churn probability, Risk."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output file with exact schema/order: "
            "State, Customer name, Customer mobile number, Churn probability, Risk, Potential, Potential Band."
        ),
    )
    parser.add_argument(
        "--lookup-output",
        default=None,
        help="Optional override for packaged potential lookup parquet path.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    lookup_path = Path(args.lookup_output) if args.lookup_output else Path("artifacts/production") / POTENTIAL_LOOKUP_FILENAME
    request = PotentialJobRequest(
        input_path=Path(args.input),
        output_path=Path(args.output),
        lookup_path=lookup_path,
        project_root=Path(".").resolve(),
    )
    run_potential_enrichment_job(
        request=request,
        raise_on_error=True,
    )


if __name__ == "__main__":
    main()
