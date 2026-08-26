import unittest

import pandas as pd

from src.partA1serving.data_source import A1DataBundle
from src.partA1serving.feature_service import FeatureService, PredictRequest


class MemoryDataSource:
    def __init__(self) -> None:
        self.history_cutoff = None

    def load(self, *, history_cutoff=None) -> A1DataBundle:
        self.history_cutoff = history_cutoff
        return A1DataBundle(
            customers=pd.DataFrame(
                [{
                    "customer_id": "C1", "age_group": "35-44", "city": "上海",
                    "occupation": "企业职员", "income_level": "30-50万",
                    "register_date": pd.Timestamp("2020-01-01"), "aum": 500_000.0,
                    "risk_appetite": "R3", "vip_level": "金卡", "has_app": 1,
                }]
            ),
            products=pd.DataFrame(
                [{
                    "product_id": "P1", "product_name": "测试产品", "product_type": "混合",
                    "risk_level": "R3", "expected_return": 0.05, "volatility": 0.08,
                    "min_invest": 1_000.0, "duration_days": 90, "liquidity": "T+1",
                    "launch_date": pd.Timestamp("2024-01-01"),
                }]
            ),
            campaigns=pd.DataFrame(
                [
                    {"contact_id": "K1", "customer_id": "C1", "product_id": "P1", "channel": "sms", "contact_date": pd.Timestamp("2026-04-14"), "responded": 1},
                    {"contact_id": "K2", "customer_id": "C1", "product_id": "P1", "channel": "sms", "contact_date": pd.Timestamp("2026-04-15"), "responded": 0},
                ]
            ),
            holdings=pd.DataFrame(
                [
                    {"holding_id": "H1", "customer_id": "C1", "product_id": "P1", "amount": 100.0, "buy_date": pd.Timestamp("2026-04-14")},
                    {"holding_id": "H2", "customer_id": "C1", "product_id": "P1", "amount": 999.0, "buy_date": pd.Timestamp("2026-04-15")},
                ]
            ),
            events=pd.DataFrame(
                [
                    {"event_id": "E1", "customer_id": "C1", "event_type": "consult", "event_date": pd.Timestamp("2026-04-14")},
                    {"event_id": "E2", "customer_id": "C1", "event_type": "complaint", "event_date": pd.Timestamp("2026-04-15")},
                ]
            ),
        )


class A1ServingIntegrationTestCase(unittest.TestCase):
    def test_injected_source_keeps_strict_as_of_semantics(self) -> None:
        source = MemoryDataSource()
        service = FeatureService(
            prior=0.2,
            default_as_of="2026-04-15",
            data_source=source,
        )

        bundle = service.assemble(
            PredictRequest(
                customer_id="C1",
                product_id="P1",
                channel="sms",
                contact_date="2026-04-15",
            )
        )

        row = bundle.frame.iloc[0]
        self.assertEqual(row["cust_hist_cnt"], 1)
        self.assertEqual(row["owns_this_product"], 1)
        self.assertEqual(row["hold_cnt"], 1)
        self.assertEqual(row["consult_30d"], 1)
        self.assertEqual(row["complaint_30d"], 0)


if __name__ == "__main__":
    unittest.main()
