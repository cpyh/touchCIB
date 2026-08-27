import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.marketing.models import Customer, CustomerBehavior, Product
from src.marketing.submission import generate_batches, write_outputs
from src.marketing.warehouse import MarketingWarehouseContext


class _FakePredictor:
    profile = "full"
    model_name = "lgbm_onehot"
    meta = SimpleNamespace(
        profile="full",
        model_name="lgbm_onehot",
        trained_at="2026-08-27T00:00:00",
        schema_version=3,
    )

    def __init__(self) -> None:
        self.requests = []

    def predict_batch(self, requests, *, explain=False):
        self.requests.extend(requests)
        probability = {"P001": 0.4, "P002": 0.9, "P003": 0.8, "P004": 0.7}
        return [
            SimpleNamespace(
                customer_id=request.customer_id,
                product_id=request.product_id,
                probability=probability[request.product_id],
            )
            for request in requests
        ]


def _context() -> MarketingWarehouseContext:
    customer = Customer(
        customer_id="C000001",
        age_group="35-44",
        city="上海",
        occupation="企业职员",
        income_level="30-50万",
        register_date=date(2024, 1, 1),
        aum=500_000,
        risk_appetite="R3",
        vip_level="金卡",
        has_app=True,
    )
    products = tuple(
        Product(
            product_id=f"P00{index}",
            product_name=f"产品{index}",
            product_type="混合",
            risk_level="R3",
            expected_return=0.03,
            volatility=0.02,
            min_invest=10_000,
            duration_days=90,
            liquidity="T+1",
            launch_date=date(2025, 1, 1),
        )
        for index in range(1, 5)
    )
    return MarketingWarehouseContext(
        customers={customer.customer_id: customer},
        products=products,
        behaviors={customer.customer_id: CustomerBehavior(customer.customer_id)},
        strategy_date=date(2026, 4, 15),
    )


class MarketingSubmissionTestCase(unittest.TestCase):
    @patch("src.marketing.submission.load_marketing_context", return_value=_context())
    def test_submission_scores_complete_product_pool_before_top3(self, _load_context):
        predictor = _FakePredictor()
        batches = generate_batches(
            {"C000001": date(2026, 4, 15)},
            predictor=predictor,
            data_source=SimpleNamespace(),
        )

        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0].score_rows), 4)
        self.assertEqual(len(batches[0].decision_rows), 4)
        self.assertEqual(len(batches[0].strategy_rows), 3)
        self.assertEqual(
            {request.product_id for request in predictor.requests},
            {"P001", "P002", "P003", "P004"},
        )

    @patch("src.marketing.submission.load_marketing_context", return_value=_context())
    def test_audit_contains_current_a1_and_rule_fields_without_ltr(self, _load_context):
        batches = generate_batches(
            {"C000001": date(2026, 4, 15)},
            predictor=_FakePredictor(),
            data_source=SimpleNamespace(),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "partA_strategy.csv"
            audit = Path(directory) / "a2_strategy_audit.csv"
            write_outputs(output, audit, batches)

            with output.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            with audit.open(encoding="utf-8", newline="") as file:
                audit_rows = list(csv.DictReader(file))

            self.assertEqual(len(rows), 3)
            self.assertEqual(len(audit_rows), 3)
            self.assertIn("model_prob", audit_rows[0])
            self.assertIn("rule_version", audit_rows[0])
            self.assertNotIn("ltr_score", audit_rows[0])


if __name__ == "__main__":
    unittest.main()

