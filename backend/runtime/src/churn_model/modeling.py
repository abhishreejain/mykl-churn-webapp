"""Model training utilities for the four approved model families."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from churn_model.feature_engineering import CATEGORICAL_FEATURES, NUMERIC_FEATURES, build_features


APPROVED_MODEL_NAMES = ["xgboost", "random_forest", "logistic_regression", "hist_gradient_boosting"]


def build_preprocessor(scale_numeric: bool = False) -> ColumnTransformer:
    numeric_steps: list[tuple[str, object]] = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    numeric_pipeline = Pipeline(numeric_steps)
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="constant", fill_value="UNKNOWN")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, NUMERIC_FEATURES),
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
        ]
    )


def class_imbalance_ratio(y: pd.Series) -> float:
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    if positives == 0:
        return 1.0
    return max(1.0, negatives / positives)


def balanced_sample_weight(y: pd.Series) -> np.ndarray:
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    total = len(y)
    if positives == 0 or negatives == 0:
        return np.ones(total)
    return np.where(y.to_numpy() == 1, total / (2 * positives), total / (2 * negatives))


def build_approved_models(random_state: int, y_train: pd.Series) -> dict[str, Pipeline]:
    imbalance = class_imbalance_ratio(y_train)
    return {
        "xgboost": Pipeline(
            [
                ("preprocessor", build_preprocessor(scale_numeric=False)),
                (
                    "model",
                    XGBClassifier(
                        n_estimators=500,
                        max_depth=4,
                        learning_rate=0.05,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        objective="binary:logistic",
                        eval_metric="logloss",
                        scale_pos_weight=imbalance,
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("preprocessor", build_preprocessor(scale_numeric=False)),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=400,
                        min_samples_leaf=20,
                        class_weight="balanced_subsample",
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "logistic_regression": Pipeline(
            [
                ("preprocessor", build_preprocessor(scale_numeric=True)),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        solver="saga",
                        n_jobs=-1,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("preprocessor", build_preprocessor(scale_numeric=False)),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        learning_rate=0.05,
                        max_iter=400,
                        l2_regularization=0.01,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }


def maybe_calibrate_model(model: Pipeline, x_cal: pd.DataFrame, y_cal: pd.Series, enabled: bool) -> object:
    """Optionally calibrate probabilities on validation data.

    Calibration is disabled unless explicitly requested by the model-selection
    strategy. This keeps the default comparison simple and reproducible.
    """
    if not enabled:
        return model
    try:
        return CalibratedClassifierCV(model, method="isotonic", cv="prefit").fit(x_cal, y_cal)
    except TypeError:
        return CalibratedClassifierCV(model, method="isotonic", cv="prefit").fit(x_cal, y_cal)


def predict_probability(model: object, features: pd.DataFrame) -> np.ndarray:
    if not hasattr(model, "predict_proba"):
        raise TypeError("Model does not expose predict_proba")
    return model.predict_proba(features)[:, 1]


def save_model(model: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return path


def load_model(path: Path) -> object:
    return joblib.load(path)


def build_model(random_state: int = 42) -> Pipeline:
    """Backward-compatible default model builder."""
    dummy_y = pd.Series([0, 1])
    return build_approved_models(random_state, dummy_y)["random_forest"]


def train_model(labeled_windows: pd.DataFrame) -> object:
    if "target" not in labeled_windows.columns:
        raise ValueError("labeled_windows must include a target column")
    features = build_features(labeled_windows)
    model = build_model()
    model.fit(features, labeled_windows["target"].astype(int))
    return model
