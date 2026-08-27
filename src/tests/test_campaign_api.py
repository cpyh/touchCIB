import unittest
from datetime import datetime
from unittest.mock import patch

from src.app import app


class CampaignEventApiTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("src.app.create_sent_event")
    def test_sent_defaults_to_selected_business_date(self, mock_create):
        mock_create.return_value = {
            "campaign_event_id": 1,
            "strategy_id": "C000001:1",
            "event_type": "sent",
            "occurred_at": "2026-04-15T10:00:00",
        }

        response = self.client.post(
            "/campaign/events",
            json={
                "event_type": "sent",
                "strategy_id": "C000001:1",
                "business_date": "2026-04-15",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            mock_create.call_args.kwargs["occurred_at"],
            datetime(2026, 4, 15, 10, 0),
        )

    @patch("src.app.create_sent_event")
    def test_sent_rejects_time_outside_business_date(self, mock_create):
        response = self.client.post(
            "/campaign/events",
            json={
                "event_type": "sent",
                "strategy_id": "C000001:1",
                "business_date": "2026-04-15",
                "occurred_at": "2026-08-27T10:00:00",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("当前业务日期", response.get_json()["error"])
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
