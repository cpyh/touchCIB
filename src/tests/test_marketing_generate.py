import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from src.marketing.generate import StrategyGenerationError, generate_customer_strategy
from src.marketing.models import Customer, CustomerBehavior, Product
from src.marketing.warehouse import MarketingWarehouseContext


class FakePredictor:
    profile = "full"
    model_name = "fake_a1"
    meta = SimpleNamespace(
        profile="full",
        model_name="fake_a1",
        trained_at="2026-08-27T00:00:00",
        schema_version=3,
    )

    def __init__(self):
        self.requests = []

    def predict_batch(self, requests, *, explain=False):
        self.requests.extend(requests)
        return [
            SimpleNamespace(
                customer_id=request.customer_id,
                product_id=request.product_id,
                probability={"P001": 0.7, "P002": 0.9, "P003": 0.8, "P004": 0.99}[
                    request.product_id
                ],
            )
            for request in requests
        ]


def context() -> MarketingWarehouseContext:
    customer = Customer(
        customer_id="C000010",
        age_group="35-44",
        city="上海",
        occupation="企业职员",
        income_level="30-50万",
        register_date=date(2024, 1, 1),
        aum=500_000,
        risk_appetite="R2",
        vip_level="金卡",
        has_app=True,
    )
    products = tuple(
        Product(
            product_id=f"P00{index}",
            product_name=f"产品{index}",
            product_type="混合",
            risk_level="R5" if index == 4 else "R2",
            expected_return=0.03 + index / 100,
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


class MarketingGenerateTestCase(unittest.TestCase):
    @patch("src.marketing.generate.load_marketing_context", return_value=context())
    def test_generate_returns_top3_with_trace(self, _mock_context):
        result = generate_customer_strategy(
            "C000010", response_predictor=FakePredictor()
        )
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual([item["rank"] for item in result["items"]], [1, 2, 3])
        self.assertEqual(result["parameters"]["ranking_source"], "a1_probability")
        for item in result["items"]:
            self.assertIn("model_prob", item)
            self.assertGreater(len(item["rule_trace"]), 0)
            self.assertTrue(10 <= len(item["marketing_script"]) <= 300)

    @patch("src.marketing.generate.load_marketing_context", return_value=context())
    def test_manager_quota_zero_disables_manager_channel(self, _mock_context):
        result = generate_customer_strategy(
            "C000010", manager_quota=0, response_predictor=FakePredictor()
        )
        self.assertNotIn(
            "manager", {item["recommended_channel"] for item in result["items"]}
        )

    @patch(
        "src.marketing.generate.load_marketing_context",
        side_effect=ValueError("客户不存在：C999999"),
    )
    def test_unknown_customer_rejected(self, _mock_context):
        with self.assertRaises(StrategyGenerationError):
            generate_customer_strategy(
                "C999999", response_predictor=FakePredictor()
            )

    @patch("src.marketing.generate.load_marketing_context", return_value=context())
    def test_live_predictor_scores_complete_context_product_pool(self, _mock_context):
        predictor = FakePredictor()
        result = generate_customer_strategy(
            "C000010", response_predictor=predictor
        )

        self.assertEqual(result["parameters"]["a1_source"], "mysql_dwd_online")
        self.assertEqual(
            {request.product_id for request in predictor.requests},
            {"P001", "P002", "P003", "P004"},
        )
        self.assertTrue(all(item["model_prob"] > 0 for item in result["items"]))


if __name__ == "__main__":
    unittest.main()
