import unittest
from types import SimpleNamespace

from src.marketing.generate import (
    StrategyGenerationError,
    generate_customer_strategy,
)


class MarketingGenerateTestCase(unittest.TestCase):
    def test_generate_returns_top3_with_trace(self):
        result = generate_customer_strategy("C000010")
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual([item["rank"] for item in result["items"]], [1, 2, 3])
        self.assertEqual(
            result["parameters"]["ranking_source"], "ltr"
        )
        for item in result["items"]:
            self.assertIn("score", item)
            self.assertIn("model_prob", item)
            self.assertIn("ltr_score", item)
            self.assertIn("rule_trace", item)
            self.assertGreater(len(item["rule_trace"]), 0)
            self.assertTrue(10 <= len(item["marketing_script"]) <= 300)

    def test_manager_quota_zero_disables_manager_channel(self):
        result = generate_customer_strategy("C000010", manager_quota=0)
        channels = {item["recommended_channel"] for item in result["items"]}
        self.assertNotIn("manager", channels)

    def test_unknown_customer_rejected(self):
        with self.assertRaises(StrategyGenerationError):
            generate_customer_strategy("C999999")

    def test_live_predictor_scores_complete_product_pool(self):
        class FakePredictor:
            requests = []

            def predict_batch(self, requests):
                self.requests.extend(requests)
                return [
                    SimpleNamespace(
                        product_id=request.product_id,
                        probability=int(request.product_id[1:]) / 100,
                    )
                    for request in requests
                ]

        predictor = FakePredictor()
        result = generate_customer_strategy(
            "C000010",
            response_predictor=predictor,
        )

        self.assertEqual(result["parameters"]["a1_source"], "mysql_serving")
        self.assertEqual(
            {request.product_id for request in predictor.requests},
            {f"P{index:03d}" for index in range(1, 31)},
        )
        self.assertTrue(all(item["model_prob"] > 0 for item in result["items"]))


if __name__ == "__main__":
    unittest.main()
