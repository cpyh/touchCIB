import unittest
from unittest.mock import patch

from src.marketing.tasks import _task_frame, query_marketing_tasks


class MarketingTasksTestCase(unittest.TestCase):
    def test_base_frame_is_customer_grained(self):
        frame = _task_frame()
        self.assertEqual(len(frame), 8000)
        self.assertEqual(frame["customer_id"].nunique(), 8000)
        self.assertEqual(int(frame["official_target"].sum()), 2000)
        self.assertTrue((frame.loc[frame["official_target"], "rank"] == 1).all())
        self.assertEqual(int(frame["response_prob"].notna().sum()), 5031)

    @patch("src.marketing.tasks._live_strategy_customers", return_value=frozenset())
    @patch("src.marketing.tasks._event_statuses")
    def test_status_filter_and_counts(self, mock_statuses, _mock_live):
        customer_ids = _task_frame()["customer_id"].head(2).tolist()
        mock_statuses.return_value = {
            customer_ids[0]: "follow_up",
            customer_ids[1]: "converted",
        }

        result = query_marketing_tasks(status="follow_up", size=10)

        self.assertEqual(result["counts"]["all"], 8000)
        self.assertEqual(result["counts"]["follow_up"], 1)
        self.assertEqual(result["counts"]["converted"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["tasks"][0]["customer_id"], customer_ids[0])

    @patch("src.marketing.tasks._live_strategy_customers", return_value=frozenset())
    @patch("src.marketing.tasks._event_statuses", return_value={})
    def test_non_a2_customer_is_listed_for_live_strategy(
        self, _mock_statuses, _mock_live
    ):
        result = query_marketing_tasks(status="pending", keyword="C000001", size=10)
        self.assertEqual(result["total"], 1)
        task = result["tasks"][0]
        self.assertFalse(task["official_target"])
        self.assertFalse(task["strategy_ready"])
        self.assertEqual(task["strategy_source"], "live_on_demand")
        self.assertIsNone(task["strategy_id"])

    @patch("src.marketing.tasks._live_strategy_customers", return_value=frozenset())
    @patch("src.marketing.tasks._event_statuses", return_value={})
    def test_keyword_is_literal_not_regular_expression(
        self, _mock_statuses, _mock_live
    ):
        result = query_marketing_tasks(keyword="[", size=10)
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
