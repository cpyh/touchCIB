import unittest
from datetime import date, timedelta

from src.marketing.attribution import (
    DEFAULT_WINDOW_DAYS,
    attribute_purchase,
    find_responses,
)

STRATEGY_DATE = date(2026, 4, 15)
TOP3 = {
    "C000001": ("P001", "P002", "P003"),
    "C000002": ("P004", "P005", "P006"),
}


class AttributionTestCase(unittest.TestCase):
    def attribute(self, customer_id, product_id, buy_date, **kwargs):
        return attribute_purchase(
            customer_id=customer_id,
            product_id=product_id,
            buy_date=buy_date,
            strategy_date=STRATEGY_DATE,
            top3=TOP3,
            **kwargs,
        )

    def test_match_rank(self):
        outcome = self.attribute("C000001", "P002", date(2026, 4, 20))
        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.strategy_id, "C000001:2")
        self.assertEqual(outcome.rank, 2)

    def test_window_boundaries(self):
        # 策略日当天与窗口末日（+30 天）都在窗口内
        first_day = self.attribute("C000001", "P001", STRATEGY_DATE)
        self.assertTrue(first_day.matched)
        last_day = self.attribute(
            "C000001", "P001", STRATEGY_DATE + timedelta(days=30)
        )
        self.assertTrue(last_day.matched)
        # 第 31 天超窗
        out_of_window = self.attribute(
            "C000001", "P001", STRATEGY_DATE + timedelta(days=31)
        )
        self.assertFalse(out_of_window.matched)
        self.assertIn("超出归因窗口", out_of_window.reason)

    def test_purchase_before_strategy_rejected(self):
        outcome = self.attribute("C000001", "P001", date(2026, 4, 14))
        self.assertFalse(outcome.matched)
        self.assertIn("触达前购买", outcome.reason)

    def test_product_not_in_top3_rejected(self):
        outcome = self.attribute("C000001", "P099", date(2026, 4, 20))
        self.assertFalse(outcome.matched)
        self.assertIn("Top3", outcome.reason)

    def test_unknown_customer_rejected(self):
        outcome = self.attribute("C999999", "P001", date(2026, 4, 20))
        self.assertFalse(outcome.matched)
        self.assertIn("不在目标名单", outcome.reason)

    def test_custom_window_days(self):
        buy = STRATEGY_DATE + timedelta(days=10)
        ok = self.attribute("C000001", "P001", buy, window_days=10)
        self.assertTrue(ok.matched)
        # 窗口参数收紧后，超出 7 天的购买被拒
        rejected = self.attribute("C000001", "P001", buy, window_days=7)
        self.assertFalse(rejected.matched)

    def test_invalid_window_raises(self):
        with self.assertRaises(ValueError):
            self.attribute("C000001", "P001", STRATEGY_DATE, window_days=0)
        with self.assertRaises(ValueError):
            self.attribute("C000001", "P001", STRATEGY_DATE, window_days=366)

    def test_find_responses_batch(self):
        purchases = [
            ("C000001", "P001", date(2026, 4, 20)),   # 命中
            ("C000001", "P099", date(2026, 4, 20)),   # 非 Top3
            ("C000002", "P005", date(2026, 6, 1)),    # 窗口外
        ]
        outcomes = find_responses(
            purchases, strategy_date=STRATEGY_DATE, top3=TOP3
        )
        self.assertEqual(len(outcomes), 3)
        self.assertTrue(outcomes[0].matched)
        self.assertFalse(outcomes[1].matched)
        self.assertFalse(outcomes[2].matched)


if __name__ == "__main__":
    unittest.main()
