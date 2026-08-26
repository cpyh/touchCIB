import unittest
from unittest.mock import patch

from src.app import app


class FakePredictor:
    def predict_dict(self, payload):
        return {
            "customer_id": payload["customer_id"],
            "product_id": payload["product_id"],
            "channel": payload["channel"],
            "probability": 0.72,
            "decision": "HIGH",
            "decision_label": "建议优先触达",
            "reasons": ["测试解释"],
        }


class A1ServingApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("src.app.get_mysql_predictor", return_value=FakePredictor())
    def test_predict_endpoint_uses_serving_predictor(self, _predictor) -> None:
        response = self.client.post(
            "/marketing/response/predict",
            json={
                "customer_id": "C000001",
                "product_id": "P002",
                "channel": "manager",
                "contact_date": "2026-04-15",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["probability"], 0.72)


if __name__ == "__main__":
    unittest.main()
