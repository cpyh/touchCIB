import unittest
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from src.algorithms.partb import (
    build_covariance_matrix,
    build_masks,
    load_correlation_matrix,
    load_products,
    read_dict_csv,
)
from src.app import app


DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "data" / "raw"


@lru_cache(maxsize=1)
def csv_optimizer_context():
    products = load_products(DATA_DIR)
    correlation = load_correlation_matrix(DATA_DIR, products.product_ids)
    covariance = build_covariance_matrix(products.volatility, correlation)
    high_risk_mask, non_liquid_mask = build_masks(products)
    details = {
        row["product_id"]: row for row in read_dict_csv(DATA_DIR / "t_product.csv")
    }
    return products, covariance, high_risk_mask, non_liquid_mask, details


class PortfolioEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.context_patch = patch(
            "src.portfolio.optimizer_context",
            return_value=csv_optimizer_context(),
        )
        self.context_patch.start()

    def tearDown(self) -> None:
        self.context_patch.stop()

    def test_optimize_one_scenario(self) -> None:
        response = self.client.post(
            "/portfolio/optimize",
            json={
                "total_amount": 500000,
                "risk_aversion": 0.94,
                "max_single_weight": 0.3,
                "max_high_risk_weight": 0.5,
                "min_liquid_weight": 0.2,
                "min_holdings": 4,
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertGreaterEqual(result["summary"]["holdings_count"], 4)
        self.assertLessEqual(result["summary"]["invested_weight"], 1.000001)
        self.assertEqual(
            len(result["allocations"]),
            result["summary"]["holdings_count"],
        )
        self.assertGreater(len(result["allocations"]), 0)

    def test_rejects_invalid_min_holdings(self) -> None:
        response = self.client.post(
            "/portfolio/optimize",
            json={
                "total_amount": 500000,
                "risk_aversion": 0.94,
                "max_single_weight": 0.3,
                "max_high_risk_weight": 0.5,
                "min_liquid_weight": 0.2,
                "min_holdings": 31,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("min_holdings", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
