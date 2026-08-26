import unittest
from datetime import date
from decimal import Decimal

from backend.app.services.profile_service import build_asset_profile, build_behavior_profile


class ProfileAggregationTestCase(unittest.TestCase):
    def setUp(self):
        self.customer = {
            "customer_id": "C1",
            "aum": Decimal("1000000"),
            "risk_appetite": "R2",
            "has_app": True,
        }

    def test_aggregates_holdings(self):
        rows = [
            {
                "holding_id": "H1",
                "product_id": "P1",
                "product_name": "产品一",
                "product_type": "现金管理",
                "risk_level": "R1",
                "liquidity": "T+0",
                "amount": Decimal("60000"),
                "buy_date": date(2026, 1, 1),
                "expected_return": Decimal("0.02"),
            },
            {
                "holding_id": "H2",
                "product_id": "P2",
                "product_name": "产品二",
                "product_type": "混合",
                "risk_level": "R3",
                "liquidity": "封闭",
                "amount": Decimal("40000"),
                "buy_date": date(2026, 2, 1),
                "expected_return": Decimal("0.08"),
            },
        ]
        result = build_asset_profile(self.customer, rows)
        self.assertEqual(result["holding_amount"], 100000.0)
        self.assertEqual(result["holding_product_count"], 2)
        self.assertEqual(result["high_liquidity_ratio"], 0.6)
        self.assertEqual(result["weighted_expected_return"], 0.044)

    def test_builds_behavior_tags(self):
        events = [
            {"event_type": "login", "event_date": date(2026, 3, 20)} for _ in range(5)
        ]
        result = build_behavior_profile(
            self.customer,
            events,
            {"high_liquidity_ratio": 0.6},
            date(2026, 3, 31),
        )
        self.assertIn("高净值客户", result["tags"])
        self.assertIn("近期活跃", result["tags"])


if __name__ == "__main__":
    unittest.main()
