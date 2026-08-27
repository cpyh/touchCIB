#!/usr/bin/env python3
"""提交前校验：校验根目录三份正式 CSV 与题目红线的一致性。

本仓库根目录即赛事提交包，三份 CSV 位于根目录：
    partA_prediction.csv / partA_strategy.csv / partB_allocation.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.marketing.validate import validate_strategy_file  # noqa: E402
from src.algorithms.partb import (  # noqa: E402
    build_covariance_matrix,
    build_masks,
    load_correlation_matrix,
    load_products,
    load_scenarios,
    verify_written_allocation,
)

DATA_DIR = PROJECT_DIR / "src" / "data" / "raw"
OFFICIAL_FILES = {
    "a1": PROJECT_DIR / "partA_prediction.csv",
    "a2": PROJECT_DIR / "partA_strategy.csv",
    "part_b": PROJECT_DIR / "partB_allocation.csv",
}


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"required file is missing: {path}")


def validate_prediction_file(
    output_path: Path, expected_contacts: pd.DataFrame
) -> None:
    """校验 A1 提交文件的字段、覆盖范围与概率边界。"""
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
    if probabilities.isna().any() or not probabilities.between(0, 1).all():
        raise ValueError("prediction probability is outside [0, 1]")


def validate_a1() -> None:
    path = OFFICIAL_FILES["a1"]
    require_file(path)
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("partA_prediction.csv exceeds 5 MiB")
    contacts = pd.read_csv(
        DATA_DIR / "partA_test_contacts.csv", dtype={"contact_id": str}
    )
    validate_prediction_file(path, contacts)


def validate_a2() -> None:
    path = OFFICIAL_FILES["a2"]
    require_file(path)
    customers = pd.read_csv(
        DATA_DIR / "partA_strategy_customers.csv", dtype={"customer_id": str}
    )
    expected = set(customers["customer_id"])
    errors = validate_strategy_file(path, expected_customers=expected)
    if errors:
        raise ValueError(
            "partA_strategy.csv validation failed: " + "; ".join(errors)
        )


def validate_part_b() -> float:
    path = OFFICIAL_FILES["part_b"]
    require_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header = next(reader, None)
    if header != ["scenario_id", "product_id", "weight"]:
        raise ValueError(f"partB_allocation.csv has invalid columns: {header}")

    products = load_products(DATA_DIR)
    scenarios = load_scenarios(DATA_DIR)
    correlation = load_correlation_matrix(DATA_DIR, products.product_ids)
    sigma = build_covariance_matrix(products.volatility, correlation)
    high_risk_mask, non_liquid_mask = build_masks(products)
    return verify_written_allocation(
        path,
        scenarios,
        products,
        sigma,
        high_risk_mask,
        non_liquid_mask,
    )


def main() -> int:
    validate_a1()
    print("[PASS] partA_prediction.csv")
    validate_a2()
    print("[PASS] partA_strategy.csv")
    total_utility = validate_part_b()
    print(f"[PASS] partB_allocation.csv total_U={total_utility:.15f}")
    print("三份正式 CSV 全部通过题目红线校验。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
