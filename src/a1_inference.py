"""Batch inference, explanation audit, and official CSV output for Part A1."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy import sparse

from .a1_features import (
    EVIDENCE_FEATURES,
    FEATURE_VERSION,
    MODEL_FEATURES,
    build_contact_features,
    load_csv_sources,
)
from .database import database_connection


PROJECT_DIR = Path(__file__).resolve().parents[1]

SOURCE_QUERIES = {
    "customers": (
        "SELECT customer_id, age_group, city, occupation, income_level, "
        "register_date, aum, risk_appetite, vip_level, has_app "
        "FROM dwd_dim_customer"
    ),
    "products": (
        "SELECT product_id, product_name, product_type, risk_level, "
        "expected_return, volatility, min_invest, duration_days, liquidity, "
        "launch_date FROM dwd_dim_product"
    ),
    "holdings": (
        "SELECT holding_id, customer_id, product_id, amount, buy_date "
        "FROM dwd_fact_holding"
    ),
    "campaigns": (
        "SELECT contact_id, customer_id, product_id, channel, contact_date, "
        "responded FROM dwd_fact_campaign"
    ),
    "events": (
        "SELECT event_id, customer_id, event_type, event_date "
        "FROM dwd_fact_event"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Part A1 batch inference")
    parser.add_argument(
        "--contacts",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "raw" / "partA_test_contacts.csv",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "outputs" / "a1_baseline.joblib",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "partA_prediction.csv",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "outputs" / "a1_prediction_audit.csv",
    )
    parser.add_argument(
        "--source",
        choices=("mysql", "csv"),
        default="mysql",
        help="Read feature sources from DWD MySQL tables or official CSV files",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=PROJECT_DIR / "src" / "data" / "raw"
    )
    parser.add_argument(
        "--persist-db",
        action="store_true",
        help="Upsert scores and explanation evidence into the ADS table",
    )
    return parser.parse_args()


def load_mysql_sources() -> dict[str, pd.DataFrame]:
    connection = database_connection()
    try:
        sources: dict[str, pd.DataFrame] = {}
        with connection.cursor() as cursor:
            for name, query in SOURCE_QUERIES.items():
                cursor.execute(query)
                sources[name] = pd.DataFrame(cursor.fetchall())
    finally:
        connection.close()
    empty = [name for name, frame in sources.items() if frame.empty]
    if empty:
        raise RuntimeError(f"DWD source tables are empty: {empty}")
    return sources


def _json_value(value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def _display_feature_name(name: str) -> str:
    for prefix in ("categorical__", "numeric__"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def local_explanations(
    pipeline: Any,
    feature_rows: pd.DataFrame,
    probabilities: np.ndarray,
    *,
    top_n: int = 5,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    preprocessor = pipeline.named_steps["preprocessor"]
    classifier = pipeline.named_steps["classifier"]
    transformed = preprocessor.transform(feature_rows[MODEL_FEATURES])
    names = np.asarray(preprocessor.get_feature_names_out(), dtype=object)
    coefficients = classifier.coef_[0]
    model_scores = np.asarray(
        pipeline.decision_function(feature_rows[MODEL_FEATURES]), dtype=float
    )

    explanations: list[dict[str, Any]] = []
    for index in range(len(feature_rows)):
        if sparse.issparse(transformed):
            row = transformed.getrow(index)
            feature_indexes = row.indices
            contributions = row.data * coefficients[feature_indexes]
        else:
            values = np.asarray(transformed[index], dtype=float)
            feature_indexes = np.flatnonzero(values)
            contributions = values[feature_indexes] * coefficients[feature_indexes]

        positive_order = np.argsort(-contributions)
        negative_order = np.argsort(contributions)

        def factors(order: np.ndarray, *, positive: bool) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for position in order:
                contribution = float(contributions[position])
                if (positive and contribution <= 0) or (
                    not positive and contribution >= 0
                ):
                    continue
                feature_index = int(feature_indexes[position])
                result.append(
                    {
                        "feature": _display_feature_name(str(names[feature_index])),
                        "contribution": round(contribution, 6),
                    }
                )
                if len(result) == top_n:
                    break
            return result

        row = feature_rows.iloc[index]
        evidence = {
            name: _json_value(row[name])
            for name in EVIDENCE_FEATURES
        }
        explanations.append(
            {
                "response_prob": round(float(probabilities[index]), 12),
                "model_score": round(float(model_scores[index]), 12),
                "top_positive_factors": factors(positive_order, positive=True),
                "top_negative_factors": factors(negative_order, positive=False),
                "evidence": evidence,
            }
        )
    return model_scores, explanations


def validate_prediction_file(
    output_path: Path, expected_contacts: pd.DataFrame
) -> None:
    written = pd.read_csv(output_path, dtype={"contact_id": str})
    if list(written.columns) != ["contact_id", "response_prob"]:
        raise ValueError("prediction columns must be contact_id,response_prob")
    if len(written) != len(expected_contacts):
        raise ValueError("prediction row count does not match test contacts")
    if written["contact_id"].duplicated().any():
        raise ValueError("prediction contains duplicate contact_id values")
    if set(written["contact_id"]) != set(expected_contacts["contact_id"]):
        raise ValueError("prediction contact_id coverage is not exact")
    probabilities = pd.to_numeric(written["response_prob"], errors="raise")
    if not np.isfinite(probabilities).all():
        raise ValueError("prediction contains NaN or infinite probabilities")
    if not probabilities.between(0, 1, inclusive="both").all():
        raise ValueError("prediction probability is outside [0, 1]")


def write_audit(
    output_path: Path,
    feature_rows: pd.DataFrame,
    explanations: list[dict[str, Any]],
    *,
    model_version: str,
    feature_version: str,
) -> None:
    records = []
    for (_, row), explanation in zip(feature_rows.iterrows(), explanations):
        records.append(
            {
                "contact_id": row["contact_id"],
                "customer_id": row["customer_id"],
                "product_id": row["product_id"],
                "channel": row["channel"],
                "contact_date": row["contact_date"].date().isoformat(),
                "response_prob": explanation["response_prob"],
                "model_score": explanation["model_score"],
                "model_version": model_version,
                "feature_version": feature_version,
                "feature_as_of_date": row["contact_date"].date().isoformat(),
                "top_positive_factors": json.dumps(
                    explanation["top_positive_factors"], ensure_ascii=False
                ),
                "top_negative_factors": json.dumps(
                    explanation["top_negative_factors"], ensure_ascii=False
                ),
                "evidence_json": json.dumps(
                    explanation["evidence"], ensure_ascii=False
                ),
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(output_path, index=False)


def persist_scores(
    feature_rows: pd.DataFrame,
    explanations: list[dict[str, Any]],
    *,
    model_version: str,
    feature_version: str,
) -> None:
    rows = []
    for (_, row), explanation in zip(feature_rows.iterrows(), explanations):
        explanation_json = json.dumps(explanation, ensure_ascii=False)
        rows.append(
            (
                row["contact_id"],
                row["customer_id"],
                row["product_id"],
                row["channel"],
                row["contact_date"].date(),
                explanation["response_prob"],
                model_version,
                feature_version,
                row["contact_date"].date(),
                explanation_json,
            )
        )
    statement = (
        "INSERT INTO ads_marketing_response_score "
        "(contact_id, customer_id, product_id, channel, contact_date, "
        "response_prob, model_version, feature_version, feature_as_of_date, "
        "explanation_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "AS new ON DUPLICATE KEY UPDATE "
        "customer_id = new.customer_id, product_id = new.product_id, "
        "channel = new.channel, contact_date = new.contact_date, "
        "response_prob = new.response_prob, model_version = new.model_version, "
        "feature_version = new.feature_version, "
        "feature_as_of_date = new.feature_as_of_date, "
        "explanation_json = new.explanation_json, generated_at = CURRENT_TIMESTAMP"
    )
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            for offset in range(0, len(rows), 1_000):
                cursor.executemany(statement, rows[offset : offset + 1_000])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def run(args: argparse.Namespace) -> None:
    if not args.model.is_file():
        raise FileNotFoundError(f"model artifact not found: {args.model}")
    artifact = joblib.load(args.model)
    if artifact.get("feature_version") != FEATURE_VERSION:
        raise ValueError("model and inference feature versions do not match")
    if artifact.get("model_features") != MODEL_FEATURES:
        raise ValueError("model and inference feature columns do not match")

    contacts = pd.read_csv(
        args.contacts,
        dtype={"contact_id": str, "customer_id": str, "product_id": str},
    )
    sources = (
        load_mysql_sources()
        if args.source == "mysql"
        else load_csv_sources(args.data_dir)
    )
    feature_rows = build_contact_features(
        contacts,
        customers=sources["customers"],
        products=sources["products"],
        holdings=sources["holdings"],
        events=sources["events"],
        campaign_history=sources["campaigns"],
    )

    pipeline = artifact["pipeline"]
    probabilities = np.asarray(
        pipeline.predict_proba(feature_rows[MODEL_FEATURES])[:, 1], dtype=float
    )
    if not np.isfinite(probabilities).all() or not (
        (probabilities >= 0) & (probabilities <= 1)
    ).all():
        raise RuntimeError("model produced invalid probabilities")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "contact_id": feature_rows["contact_id"],
            "response_prob": [f"{value:.12f}" for value in probabilities],
        }
    ).to_csv(args.output, index=False)
    validate_prediction_file(args.output, contacts)

    _, explanations = local_explanations(pipeline, feature_rows, probabilities)
    write_audit(
        args.audit_output,
        feature_rows,
        explanations,
        model_version=artifact["model_version"],
        feature_version=artifact["feature_version"],
    )
    if args.persist_db:
        persist_scores(
            feature_rows,
            explanations,
            model_version=artifact["model_version"],
            feature_version=artifact["feature_version"],
        )

    print(f"rows={len(feature_rows)}")
    print(f"probability_min={probabilities.min():.12f}")
    print(f"probability_max={probabilities.max():.12f}")
    print(f"prediction={args.output}")
    print(f"audit={args.audit_output}")
    print(f"persisted_to_ads={args.persist_db}")


def main() -> int:
    args = parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
