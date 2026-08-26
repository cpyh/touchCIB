import unittest

from src.scripts.seed_demo_events import _pick_targets


class SeedDemoEventsTestCase(unittest.TestCase):
    def test_picks_distinct_rank1_manager_customers_sorted(self):
        frame = _pick_targets(30)
        self.assertEqual(len(frame), 30)
        self.assertEqual(frame["customer_id"].nunique(), 30)
        self.assertTrue((frame["rank"] == "1").all())
        self.assertTrue((frame["recommended_channel"] == "manager").all())
        self.assertEqual(
            frame["customer_id"].tolist(),
            sorted(frame["customer_id"].tolist()),
        )

    def test_picks_more_than_available_raises(self):
        with self.assertRaises(SystemExit):
            _pick_targets(99999)

    def test_responded_exceeds_sent_raises(self):
        from src.scripts.seed_demo_events import seed

        with self.assertRaises(SystemExit):
            seed(sent=10, responded=11)


if __name__ == "__main__":
    unittest.main()
