#!/usr/bin/env python3
"""Train and validate the reproducible Part A1 logistic-regression baseline."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.a1_features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_VERSION,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    build_contact_features,
    load_csv_sources,
)


RANDOM_STATE = 42
MODEL_VERSION = "a1_logistic_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the Part A1 baseline model")
    parser.add_argument(
        "--data-dir", type=Path, default=PROJECT_DIR / "src" / "data" / "raw"
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "outputs" / "a1_baseline.joblib",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=PROJECT_DIR
        / "src"
        / "data"
        / "outputs"
        / "a1_validation_metrics.json",
    )
    parser.add_argument(
        "--importance-output",
        type=Path,
        default=PROJECT_DIR
        / "src"
        / "data"
        / "outputs"
        / "a1_global_feature_importance.csv",
    )
    return parser.parse_args()


def model_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "onehot",
                            OneHotEncoder(handle_unknown="ignore"),
                        ),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
            (
                "numeric",
                Pipeline(
                    steps=[
                        (
                            "imputer",
                            SimpleImputer(strategy="median", add_indicator=True),
                        ),
                        ("scaler", StandardScaler()),
                    ]
                ),
                NUMERIC_FEATURES,
            ),
        ]
    )
    classifier = LogisticRegression(
        class_weight="balanced",
        max_iter=2_000,
        random_state=RANDOM_STATE,
        solver="lbfgs",
    )
    return Pipeline(
        steps=[("preprocessor", preprocessor), ("classifier", classifier)]
    )


def best_f1_at_rounded_threshold(
    labels: np.ndarray, probabilities: np.ndarray
) -> tuple[float, float]:
    rounded = np.round(probabilities, 3)
    best_f1 = -1.0
    best_threshold = 0.5
    for threshold in np.unique(rounded):
        score = f1_score(labels, rounded >= threshold, zero_division=0)
        if score > best_f1:
            best_f1 = float(score)
            best_threshold = float(threshold)
    return best_f1, best_threshold


def lift_at_ten_percent(labels: np.ndarray, probabilities: np.ndarray) -> float:
    overall_rate = float(np.mean(labels))
    if overall_rate <= 0:
        raise ValueError("validation labels contain no positive examples")
    top_count = max(1, math.ceil(len(labels) * 0.10))
    order = np.argsort(-probabilities, kind="stable")[:top_count]
    return float(np.mean(labels[order]) / overall_rate)


def write_global_importance(pipeline: Pipeline, output_path: Path) -> None:
    preprocessor = pipeline.named_steps["preprocessor"]
    classifier = pipeline.named_steps["classifier"]
    feature_names = preprocessor.get_feature_names_out()
    coefficients = classifier.coef_[0]
    importance = pd.DataFrame(
        {
            "transformed_feature": feature_names,
            "coefficient": coefficients,
            "absolute_coefficient": np.abs(coefficients),
            "direction": np.where(coefficients >= 0, "positive", "negative"),
        }
    ).sort_values("absolute_coefficient", ascending=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    importance.to_csv(output_path, index=False)


def main() -> int:
    args = parse_args()
    sources = load_csv_sources(args.data_dir)
    campaign = sources["campaigns"]
    feature_rows = build_contact_features(
        campaign,
        customers=sources["customers"],
        products=sources["products"],
        holdings=sources["holdings"],
        events=sources["events"],
        campaign_history=campaign,
    )

    labels = pd.to_numeric(feature_rows["responded"], errors="raise").astype(int)
    unique_dates = np.sort(feature_rows["contact_date"].unique())
    if len(unique_dates) < 5:
        raise ValueError("not enough unique contact dates for temporal validation")
    validation_cutoff = unique_dates[int(len(unique_dates) * 0.80)]
    train_mask = feature_rows["contact_date"] < validation_cutoff
    validation_mask = ~train_mask

    validation_model = model_pipeline()
    validation_model.fit(
        feature_rows.loc[train_mask, MODEL_FEATURES], labels.loc[train_mask]
    )
    validation_probabilities = validation_model.predict_proba(
        feature_rows.loc[validation_mask, MODEL_FEATURES]
    )[:, 1]
    validation_labels = labels.loc[validation_mask].to_numpy()
    best_f1, best_threshold = best_f1_at_rounded_threshold(
        validation_labels, validation_probabilities
    )
    metrics = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "random_state": RANDOM_STATE,
        "validation_cutoff": pd.Timestamp(validation_cutoff).date().isoformat(),
        "training_rows": int(train_mask.sum()),
        "validation_rows": int(validation_mask.sum()),
        "validation_positive_rate": float(validation_labels.mean()),
        "auc": float(roc_auc_score(validation_labels, validation_probabilities)),
        "best_f1": best_f1,
        "best_f1_threshold": best_threshold,
        "lift_at_10_percent": lift_at_ten_percent(
            validation_labels, validation_probabilities
        ),
    }

    final_model = model_pipeline()
    final_model.fit(feature_rows[MODEL_FEATURES], labels)
    artifact = {
        "pipeline": final_model,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "model_features": MODEL_FEATURES,
        "training_rows": int(len(feature_rows)),
        "training_max_contact_date": feature_rows["contact_date"]
        .max()
        .date()
        .isoformat(),
        "trained_at": datetime.now(UTC).isoformat(),
        "validation_metrics": metrics,
    }
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.model_output)

    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_global_importance(final_model, args.importance_output)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"model={args.model_output}")
    print(f"importance={args.importance_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
