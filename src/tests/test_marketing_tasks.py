import unittest
from datetime import date
from unittest.mock import patch

from src.marketing.tasks import query_marketing_tasks


def business_rows() -> list[dict]:
    return [
        {
            "customer_id": "C000001",
            "risk_appetite": "R1",
            "vip_level": "银卡",
            "aum": 100_000,
            "status": "follow_up",
            "strategy_id": "C000001:1",
            "product_id": "P010",
            "product_name": "稳健产品",
            "risk_level": "R1",
            "expected_return": 0.03,
            "recommended_channel": "call",
            "recommended_time": "工作日09:00-12:00",
            "response_prob": 0.8,
            "opportunity_product_id": "P010",
            "opportunity_product_name": "稳健产品",
            "opportunity_channel": "call",
            "opportunity_date": date(2026, 4, 15),
        },
        {
            "customer_id": "C000002",
            "risk_appetite": "R3",
            "vip_level": "金卡",
            "aum": 800_000,
            "status": "converted",
            "strategy_id": "C000002:1",
            "product_id": "P003",
            "product_name": "成长产品",
            "risk_level": "R3",
            "expected_return": 0.06,
            "recommended_channel": "manager",
            "recommended_time": "工作日12:00-14:00",
            "response_prob": 0.9,
            "opportunity_product_id": "P003",
            "opportunity_product_name": "成长产品",
            "opportunity_channel": "manager",
            "opportunity_date": date(2026, 4, 15),
        },
    ]


class MarketingTasksTestCase(unittest.TestCase):
    @patch(
        "src.marketing.tasks._latest_business_rows",
        return_value=(business_rows(), "2026-04-15", 2, 2),
    )
    def test_status_filter_and_counts(self, _mock_rows):
        result = query_marketing_tasks(status="follow_up", size=10)

        self.assertEqual(result["counts"]["all"], 2)
        self.assertEqual(result["counts"]["follow_up"], 1)
        self.assertEqual(result["counts"]["converted"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["tasks"][0]["customer_id"], "C000001")

    @patch(
        "src.marketing.tasks._latest_business_rows",
        return_value=(business_rows(), "2026-04-15", 2, 2),
    )
    def test_all_customers_use_batch_strategy_source(self, _mock_rows):
        result = query_marketing_tasks(status="all", size=10)
        self.assertEqual(result["population_total"], 2)
        self.assertEqual(result["strategy_ready_customers"], 2)
        self.assertTrue(all(task["strategy_ready"] for task in result["tasks"]))
        self.assertTrue(
            all(task["strategy_source"] == "batch_generated" for task in result["tasks"])
        )

    @patch(
        "src.marketing.tasks._latest_business_rows",
        return_value=(business_rows(), "2026-04-15", 2, 2),
    )
    def test_keyword_is_literal_not_regular_expression(self, _mock_rows):
        result = query_marketing_tasks(keyword="[", size=10)
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
