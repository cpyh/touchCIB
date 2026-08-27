import unittest
from datetime import date
from unittest.mock import patch

from src.campaign import (
    CampaignInputError,
    CampaignStoreError,
    _require_strategy_rows,
)


CUSTOMER_ID = "C000001"


def batch_rows() -> list[dict]:
    return [
        {
            "strategy_id": f"{CUSTOMER_ID}:{rank}",
            "customer_id": CUSTOMER_ID,
            "rank": rank,
            "strategy_date": date(2026, 4, 15),
            "product_id": f"P00{rank}",
        }
        for rank in (1, 2, 3)
    ]


class MarketingStrategySnapshotTestCase(unittest.TestCase):
    @patch(
        "src.campaign._known_customer_ids",
        return_value=frozenset({CUSTOMER_ID}),
    )
    @patch("src.campaign._stored_strategy_rows")
    def test_existing_ads_batch_is_returned(self, mock_stored, _mock_known):
        rows = batch_rows()
        mock_stored.return_value = rows

        self.assertEqual(_require_strategy_rows(CUSTOMER_ID), rows)

    @patch(
        "src.campaign._known_customer_ids",
        return_value=frozenset({CUSTOMER_ID}),
    )
    @patch("src.campaign._stored_strategy_rows", return_value=[])
    def test_missing_batch_does_not_generate_on_request(
        self, _mock_stored, _mock_known
    ):
        with self.assertRaisesRegex(CampaignStoreError, "请先运行营销批处理"):
            _require_strategy_rows(CUSTOMER_ID)

    @patch("src.campaign._known_customer_ids", return_value=frozenset())
    def test_unknown_customer_is_rejected(self, _mock_known):
        with self.assertRaises(CampaignInputError):
            _require_strategy_rows("C999999")


if __name__ == "__main__":
    unittest.main()
