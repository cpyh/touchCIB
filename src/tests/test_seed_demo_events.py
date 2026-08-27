import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from src.scripts.seed_demo_events import _pick_targets, seed


class SeedDemoEventsTestCase(unittest.TestCase):
    @patch("src.scripts.seed_demo_events.load_strategy_frame")
    def test_picks_distinct_rank1_manager_customers_sorted(self, mock_frame):
        mock_frame.return_value = pd.DataFrame(
            [
                {
                    "customer_id": f"C{index:06d}",
                    "rank": "1",
                    "product_id": "P001",
                    "recommended_channel": "manager",
                    "recommended_time": "工作日09:00-12:00",
                    "marketing_script": "合规营销话术",
                }
                for index in range(1, 41)
            ]
        )
        frame = _pick_targets(30)
        self.assertEqual(len(frame), 30)
        self.assertEqual(frame["customer_id"].nunique(), 30)
        self.assertTrue((frame["rank"] == "1").all())
        self.assertTrue((frame["recommended_channel"] == "manager").all())
        self.assertEqual(
            frame["customer_id"].tolist(),
            sorted(frame["customer_id"].tolist()),
        )

    @patch("src.scripts.seed_demo_events.load_strategy_frame")
    def test_picks_more_than_available_raises(self, mock_frame):
        mock_frame.return_value = pd.DataFrame(
            columns=(
                "customer_id",
                "rank",
                "product_id",
                "recommended_channel",
                "recommended_time",
                "marketing_script",
            )
        )
        with self.assertRaises(SystemExit):
            _pick_targets(99999)

    def test_responded_exceeds_sent_raises(self):
        with self.assertRaises(SystemExit):
            seed(sent=10, responded=11)

    @patch("src.scripts.seed_demo_events._existing_events", return_value={})
    @patch("src.scripts.seed_demo_events.create_responded_event")
    @patch("src.scripts.seed_demo_events.create_sent_event")
    @patch("src.scripts.seed_demo_events._pick_targets")
    def test_seed_events_are_visible_in_current_business_date(
        self,
        mock_targets,
        mock_sent,
        mock_responded,
        _mock_existing,
    ):
        mock_targets.return_value = pd.DataFrame(
            [
                {"customer_id": "C000001", "product_id": "P001"},
                {"customer_id": "C000002", "product_id": "P002"},
                {"customer_id": "C000003", "product_id": "P003"},
            ]
        )

        summary = seed(sent=3, responded=2)

        self.assertEqual(summary["responded_written"], 2)
        for call in mock_sent.call_args_list:
            self.assertEqual(call.kwargs["occurred_at"].date(), date(2026, 4, 15))
        for call in mock_responded.call_args_list:
            self.assertEqual(call.kwargs["buy_date"], date(2026, 4, 15))
            self.assertEqual(call.kwargs["occurred_at"].date(), date(2026, 4, 15))


if __name__ == "__main__":
    unittest.main()
