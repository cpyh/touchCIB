import unittest

import pandas as pd

from src.a1_features import build_contact_features


class A1FeatureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.contacts = pd.DataFrame(
            [
                {
                    "contact_id": "KT1",
                    "customer_id": "C1",
                    "product_id": "P1",
                    "channel": "app_push",
                    "contact_date": "2026-04-15",
                }
            ]
        )
        self.customers = pd.DataFrame(
            [
                {
                    "customer_id": "C1",
                    "age_group": "35-44",
                    "city": "上海",
                    "occupation": "企业职员",
                    "income_level": "30-50万",
                    "register_date": "2020-01-01",
                    "aum": 100_000,
                    "risk_appetite": "R3",
                    "vip_level": "金卡",
                    "has_app": 1,
                }
            ]
        )
        self.products = pd.DataFrame(
            [
                {
                    "product_id": "P1",
                    "product_name": "测试产品",
                    "product_type": "混合",
                    "risk_level": "R2",
                    "expected_return": 0.05,
                    "volatility": 0.08,
                    "min_invest": 1_000,
                    "duration_days": 90,
                    "liquidity": "T+1",
                    "launch_date": "2024-01-01",
                }
            ]
        )

    def test_strictly_excludes_same_day_facts(self) -> None:
        holdings = pd.DataFrame(
            [
                {
                    "holding_id": "H1",
                    "customer_id": "C1",
                    "product_id": "P1",
                    "amount": 100,
                    "buy_date": "2026-04-14",
                },
                {
                    "holding_id": "H2",
                    "customer_id": "C1",
                    "product_id": "P1",
                    "amount": 999,
                    "buy_date": "2026-04-15",
                },
            ]
        )
        events = pd.DataFrame(
            [
                {
                    "event_id": "E1",
                    "customer_id": "C1",
                    "event_type": "login",
                    "event_date": "2026-04-14",
                },
                {
                    "event_id": "E2",
                    "customer_id": "C1",
                    "event_type": "login",
                    "event_date": "2026-04-15",
                },
            ]
        )
        campaigns = pd.DataFrame(
            [
                {
                    "contact_id": "K1",
                    "customer_id": "C1",
                    "product_id": "P1",
                    "channel": "app_push",
                    "contact_date": "2026-04-14",
                    "responded": 1,
                },
                {
                    "contact_id": "K2",
                    "customer_id": "C1",
                    "product_id": "P1",
                    "channel": "app_push",
                    "contact_date": "2026-04-15",
                    "responded": 0,
                },
            ]
        )

        row = build_contact_features(
            self.contacts,
            customers=self.customers,
            products=self.products,
            holdings=holdings,
            events=events,
            campaign_history=campaigns,
        ).iloc[0]

        self.assertEqual(row["holding_total_amount"], 100)
        self.assertEqual(row["login_count_30d"], 1)
        self.assertEqual(row["days_since_last_login"], 1)
        self.assertEqual(row["prior_contact_count"], 1)
        self.assertEqual(row["prior_response_count"], 1)
        self.assertAlmostEqual(row["prior_response_rate"], 3 / 11)
        self.assertEqual(row["risk_compatible"], 1)
        self.assertEqual(row["has_app_channel_match"], 1)


if __name__ == "__main__":
    unittest.main()
