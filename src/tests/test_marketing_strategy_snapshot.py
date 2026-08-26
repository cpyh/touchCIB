import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pymysql

from src.campaign import (
    CampaignStoreError,
    _ensure_live_strategy_rows,
)


CUSTOMER_ID = "C000001"


def frozen_rows() -> list[dict]:
    return [
        {
            "strategy_id": f"{CUSTOMER_ID}:{rank}",
            "customer_id": CUSTOMER_ID,
            "rank": rank,
            "strategy_date": date(2026, 4, 15),
            "product_id": f"P00{rank}",
            "recommended_channel": "sms",
            "recommended_time": "工作日09:00-12:00",
            "marketing_script": f"策略{rank}",
            "score": 0.8 - rank / 10,
            "model_prob": 0.7 - rank / 10,
            "cf_score": 0.1,
            "overshoot": 0,
        }
        for rank in (1, 2, 3)
    ]


def generated_payload() -> dict:
    return {
        "strategy_date": "2026-04-15",
        "items": [dict(row) for row in frozen_rows()],
    }


class MarketingStrategySnapshotTestCase(unittest.TestCase):
    @patch("src.campaign._official_strategy_dates", return_value={})
    @patch("src.campaign._live_strategy_payload")
    @patch("src.campaign._stored_live_strategy_rows")
    def test_existing_snapshot_skips_generation(
        self, mock_stored, mock_generate, _mock_official
    ):
        rows = frozen_rows()
        mock_stored.return_value = rows

        self.assertEqual(_ensure_live_strategy_rows(CUSTOMER_ID), rows)
        mock_generate.assert_not_called()

    @patch("src.campaign._official_strategy_dates", return_value={})
    @patch("src.campaign.database_connection")
    @patch("src.campaign._live_strategy_payload", side_effect=lambda _customer: generated_payload())
    @patch("src.campaign._stored_live_strategy_rows")
    def test_first_access_freezes_exactly_three_rows(
        self, mock_stored, _mock_generate, mock_db, _mock_official
    ):
        rows = frozen_rows()
        mock_stored.side_effect = [[], rows]
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        mock_db.return_value = connection

        self.assertEqual(_ensure_live_strategy_rows(CUSTOMER_ID), rows)
        inserted = cursor.executemany.call_args.args[1]
        self.assertEqual(len(inserted), 3)
        self.assertEqual({row[2] for row in inserted}, {1, 2, 3})
        connection.commit.assert_called_once()

    @patch("src.campaign._official_strategy_dates", return_value={})
    @patch("src.campaign.database_connection")
    @patch("src.campaign._live_strategy_payload", side_effect=lambda _customer: generated_payload())
    @patch("src.campaign._stored_live_strategy_rows")
    def test_duplicate_key_rereads_concurrent_winner(
        self, mock_stored, _mock_generate, mock_db, _mock_official
    ):
        winner = frozen_rows()
        mock_stored.side_effect = [[], winner]
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.executemany.side_effect = pymysql.IntegrityError(1062, "duplicate")
        mock_db.return_value = connection

        self.assertEqual(_ensure_live_strategy_rows(CUSTOMER_ID), winner)
        connection.rollback.assert_called_once()

    @patch("src.campaign._official_strategy_dates", return_value={CUSTOMER_ID: date(2026, 4, 15)})
    @patch("src.campaign._stored_live_strategy_rows")
    def test_official_customer_never_writes_runtime_snapshot(
        self, mock_stored, _mock_official
    ):
        with self.assertRaisesRegex(CampaignStoreError, "禁止写入"):
            _ensure_live_strategy_rows(CUSTOMER_ID)
        mock_stored.assert_not_called()


if __name__ == "__main__":
    unittest.main()
