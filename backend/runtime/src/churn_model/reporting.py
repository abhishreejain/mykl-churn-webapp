"""Reporting helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from churn_model.io import write_csv


def write_markdown(path: Path, title: str, sections: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "# " + title + "\n\n" + "\n\n".join(sections) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def write_option_reports(
    target_options: pd.DataFrame,
    potential_options: pd.DataFrame,
    reports_dir: Path,
) -> tuple[Path, Path]:
    target_path = write_csv(target_options, reports_dir / "target_option_metrics.csv")
    potential_path = write_csv(potential_options, reports_dir / "potential_option_metrics.csv")
    return target_path, potential_path
