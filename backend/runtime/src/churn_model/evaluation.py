"""Evaluation utilities for churn model comparison."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve


DEFAULT_TOP_K_VALUES = [100, 500, 1000]


def evaluate_binary_classifier(y_true: pd.Series, y_score: pd.Series) -> dict[str, float]:
    metrics = {"pr_auc": float(average_precision_score(y_true, y_score))}
    if y_true.nunique() > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_score))
    else:
        metrics["roc_auc"] = float("nan")
    return metrics


def metrics_by_segment(
    frame: pd.DataFrame,
    score_column: str,
    label_column: str = "target",
    top_k_values: list[int] | None = None,
    dataset_name: str = "validation",
    model_name: str = "",
) -> pd.DataFrame:
    top_k_values = top_k_values or DEFAULT_TOP_K_VALUES
    rows = []
    segments = [("overall", frame)]
    if "recent_status" in frame.columns:
        for status in ["recently_scanning", "recently_inactive"]:
            segments.append((status, frame[frame["recent_status"] == status]))
    for segment, data in segments:
        if data.empty:
            continue
        y_true = data[label_column].astype(int)
        y_score = data[score_column].astype(float)
        base = evaluate_binary_classifier(y_true, y_score)
        base.update(
            {
                "dataset": dataset_name,
                "model": model_name,
                "segment": segment,
                "row_count": len(data),
                "positive_count": int(y_true.sum()),
                "positive_rate": float(y_true.mean()),
            }
        )
        rows.append(base)
        for k in top_k_values:
            if k <= len(data):
                rows.append(
                    {
                        "dataset": dataset_name,
                        "model": model_name,
                        "segment": segment,
                        "metric": f"top_{k}",
                        **precision_recall_lift_at_k(y_true, y_score, k),
                    }
                )
    return pd.DataFrame(rows)


def precision_recall_lift_at_k(y_true: pd.Series, y_score: pd.Series, k: int) -> dict[str, float]:
    ordered = pd.DataFrame({"target": y_true.to_numpy(), "score": y_score.to_numpy()}).sort_values(
        "score", ascending=False
    )
    top = ordered.head(k)
    positives = float(ordered["target"].sum())
    precision = float(top["target"].mean()) if len(top) else float("nan")
    recall = float(top["target"].sum() / positives) if positives else float("nan")
    lift = float(precision / ordered["target"].mean()) if ordered["target"].mean() else float("nan")
    return {"precision_at_k": precision, "recall_at_k": recall, "lift_at_k": lift, "k": k}


def lift_gain_table(y_true: pd.Series, y_score: pd.Series, bins: int = 10) -> pd.DataFrame:
    data = pd.DataFrame({"target": y_true.to_numpy(), "score": y_score.to_numpy()}).sort_values("score", ascending=False)
    data["bucket"] = pd.qcut(np.arange(len(data)), q=bins, labels=False, duplicates="drop") + 1
    total_positives = data["target"].sum()
    grouped = data.groupby("bucket", as_index=False).agg(rows=("target", "size"), positives=("target", "sum"))
    grouped["cumulative_rows"] = grouped["rows"].cumsum()
    grouped["cumulative_positives"] = grouped["positives"].cumsum()
    grouped["gain"] = grouped["cumulative_positives"] / total_positives if total_positives else np.nan
    grouped["lift"] = (grouped["positives"] / grouped["rows"]) / data["target"].mean() if data["target"].mean() else np.nan
    return grouped


def precision_recall_table(y_true: pd.Series, y_score: pd.Series) -> pd.DataFrame:
    precision, recall, thresholds = precision_recall_curve(y_true, y_score)
    return pd.DataFrame({"precision": precision[:-1], "recall": recall[:-1], "threshold": thresholds})


def write_comparison_plots(
    scored_frames: dict[str, pd.DataFrame],
    reports_dir: Path,
    label_column: str = "target",
    score_column: str = "risk_score",
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    _plot_pr(scored_frames, reports_dir / "pr_curve.png", label_column, score_column)
    _plot_roc(scored_frames, reports_dir / "roc_curve.png", label_column, score_column)
    _plot_lift(scored_frames, reports_dir / "lift_chart.png", label_column, score_column)


def _plot_pr(scored_frames: dict[str, pd.DataFrame], path: Path, label_column: str, score_column: str) -> None:
    plt.figure(figsize=(8, 6))
    for model, frame in scored_frames.items():
        precision, recall, _ = precision_recall_curve(frame[label_column], frame[score_column])
        plt.plot(recall, precision, label=model)
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title("Validation Precision-Recall Curves")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def _plot_roc(scored_frames: dict[str, pd.DataFrame], path: Path, label_column: str, score_column: str) -> None:
    plt.figure(figsize=(8, 6))
    for model, frame in scored_frames.items():
        if frame[label_column].nunique() < 2:
            continue
        fpr, tpr, _ = roc_curve(frame[label_column], frame[score_column])
        plt.plot(fpr, tpr, label=model)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("Validation ROC Curves")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def _plot_lift(scored_frames: dict[str, pd.DataFrame], path: Path, label_column: str, score_column: str) -> None:
    plt.figure(figsize=(8, 6))
    for model, frame in scored_frames.items():
        lift = lift_gain_table(frame[label_column], frame[score_column])
        plt.plot(lift["bucket"], lift["lift"], marker="o", label=model)
    plt.xlabel("Score Decile")
    plt.ylabel("Lift")
    plt.title("Validation Lift Chart")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
