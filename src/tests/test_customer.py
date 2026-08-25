import unittest
from unittest.mock import patch

from src.app import app


class CustomerProfileEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("src.app.get_customer_profile")
    def test_returns_customer_profile(self, get_customer_profile) -> None:
        get_customer_profile.return_value = {
            "customer_id": "C000001",
            "risk_appetite": "R1",
            "holding_amount": 10000.0,
            "response_rate": 0.5,
        }

        response = self.client.get("/customers/C000001/profile")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["customer_id"], "C000001")

    @patch("src.app.get_customer_profile", return_value=None)
    def test_returns_404_for_unknown_customer(self, _get_customer_profile) -> None:
        response = self.client.get("/customers/UNKNOWN/profile")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "customer not found"})


if __name__ == "__main__":
    unittest.main()
