import unittest
from unittest.mock import patch

import pandas as pd

from src.scripts.seed_demo_events import _pick_targets


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
        from src.scripts.seed_demo_events import seed

        with self.assertRaises(SystemExit):
            seed(sent=10, responded=11)


if __name__ == "__main__":
    unittest.main()
