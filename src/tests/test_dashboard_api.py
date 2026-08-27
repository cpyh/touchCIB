import unittest
from unittest.mock import patch

from src.app import app


class DashboardHomeApiTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("src.dashboard_api.get_home_overview")
    def test_home_endpoint_uses_business_date(self, mock_overview):
        mock_overview.return_value = {
            "business_date": "2026-04-15",
            "business_metrics": {"customer_count": 8000, "total_aum": 1.0},
            "action_items": {},
            "expiry_warning": {},
        }

        response = self.client.get(
            "/api/v1/dashboard/home?business_date=2026-04-15"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["business_date"], "2026-04-15")
        mock_overview.assert_called_once()
        self.assertEqual(mock_overview.call_args.args[0].isoformat(), "2026-04-15")

    def test_home_endpoint_rejects_invalid_business_date(self):
        response = self.client.get(
            "/api/v1/dashboard/home?business_date=2026-02-30"
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
