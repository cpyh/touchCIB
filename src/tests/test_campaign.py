import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from src.campaign import (
    CampaignInputError,
    _execution_script,
    create_responded_event,
    create_sent_event,
    simulate_holding_purchase,
)
from src.marketing.templates import COMPLIANCE_NOTE


class FakeCursor:
    """模拟 pymysql 游标：记录执行语句与参数，按序返回 fetchone/fetchall 结果。"""

    def __init__(self, fetchone_results=None, fetchall_results=None):
        self.statements: list[str] = []
        self.params_list: list[tuple] = []
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])

    def execute(self, statement, params=None):
        self.statements.append(statement)
        self.params_list.append(params or ())

    def fetchone(self):
        if self._fetchone_results:
            return self._fetchone_results.pop(0)
        return None

    def fetchall(self):
        return self._fetchall_results


def fake_connection(fetchone_results=None, fetchall_results=None):
    cursor = FakeCursor(fetchone_results, fetchall_results)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    return connection, cursor


class CampaignEventTestCase(unittest.TestCase):
    def setUp(self):
        self.customer_id = "C000001"
        self.top3 = {self.customer_id: ("P001", "P002", "P003")}
        self.strategy_id = f"{self.customer_id}:1"
        patchers = (
            patch("src.campaign._known_customer_ids", return_value=frozenset({self.customer_id})),
            patch("src.campaign.customer_top3", return_value=self.top3[self.customer_id]),
            patch("src.campaign.customer_strategy_date", return_value=date(2026, 4, 15)),
            patch("src.campaign.customer_strategy_channel", return_value="manager"),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _top3_of_first_customer(self):
        return self.top3[self.customer_id]

    def test_execution_script_adds_compliance_note_once(self):
        script, adjusted = _execution_script(
            "为您推荐稳健产品。理财非存款、产品有风险。"
        )
        self.assertTrue(adjusted)
        self.assertTrue(script.endswith(COMPLIANCE_NOTE))
        self.assertNotIn("理财非存款、产品有风险。", script)
        self.assertLessEqual(len(script), 300)

        unchanged, adjusted = _execution_script(script)
        self.assertFalse(adjusted)
        self.assertEqual(unchanged, script)

    def test_execution_script_preserves_note_when_truncated(self):
        script, adjusted = _execution_script("推荐说明" * 100)
        self.assertTrue(adjusted)
        self.assertLessEqual(len(script), 300)
        self.assertTrue(script.endswith(COMPLIANCE_NOTE))

    @patch("src.campaign.database_connection")
    def test_sent_event_recorded(self, mock_db):
        connection, cursor = fake_connection(
            fetchone_results=[
                {"campaign_event_id": 1, "strategy_id": self.strategy_id,
                 "event_type": "sent", "occurred_at": datetime(2026, 4, 16, 10, 0),
                 "product_id": None, "amount": None,
                 "created_at": datetime(2026, 4, 16, 10, 0)}
            ],
            fetchall_results=[],
        )
        mock_db.return_value = connection
        event = create_sent_event(self.strategy_id)
        self.assertEqual(event["event_type"], "sent")
        self.assertTrue(connection.commit.called)

    @patch("src.campaign.database_connection")
    def test_sent_event_invalid_strategy_id(self, mock_db):
        with self.assertRaises(CampaignInputError):
            create_sent_event("bad-format")
        with self.assertRaises(CampaignInputError):
            create_sent_event("C999999:1")
        mock_db.assert_not_called()

    @patch("src.campaign.database_connection")
    def test_sent_dedupe_customer_level(self, mock_db):
        """同一客户已有任意 rank 的 sent 事件时，重复触达被拒绝（客户口径）。"""
        connection, _ = fake_connection(
            fetchall_results=[
                {
                    "strategy_id": f"{self.customer_id}:2",
                    "event_type": "sent",
                    "occurred_at": datetime(2026, 4, 15, 9, 0),
                    "product_id": None,
                    "amount": None,
                    "created_at": datetime(2026, 4, 15, 9, 0),
                }
            ]
        )
        mock_db.return_value = connection
        with self.assertRaises(CampaignInputError) as ctx:
            create_sent_event(self.strategy_id)
        self.assertIn("只触达一次", str(ctx.exception))

    @patch("src.campaign.database_connection")
    def test_responded_attribution_rejected_outside_top3(self, mock_db):
        with self.assertRaises(CampaignInputError) as ctx:
            create_responded_event(
                customer_id=self.customer_id,
                product_id="P099",
                buy_date=date(2026, 4, 20),
            )
        self.assertIn("Top3", str(ctx.exception))
        mock_db.assert_not_called()

    @patch("src.campaign.database_connection")
    def test_responded_attribution_rejected_out_of_window(self, mock_db):
        with self.assertRaises(CampaignInputError) as ctx:
            create_responded_event(
                customer_id=self.customer_id,
                product_id=self._top3_of_first_customer()[0],
                buy_date=date(2026, 7, 1),
            )
        self.assertIn("归因窗口", str(ctx.exception))
        mock_db.assert_not_called()

    @patch("src.campaign.database_connection")
    def test_responded_duplicate_rejected(self, mock_db):
        connection, _ = fake_connection([{"count": 1}])
        mock_db.return_value = connection
        with self.assertRaises(CampaignInputError) as ctx:
            create_responded_event(
                customer_id=self.customer_id,
                product_id=self._top3_of_first_customer()[0],
                buy_date=date(2026, 4, 20),
            )
        self.assertIn("重复购买只记首次", str(ctx.exception))

    @patch("src.campaign.database_connection")
    def test_responded_recorded_with_attribution(self, mock_db):
        connection, _ = fake_connection(
            [
                {"count": 0},
                {"campaign_event_id": 2, "strategy_id": self.strategy_id,
                 "event_type": "responded",
                 "occurred_at": datetime(2026, 4, 20, 9, 30),
                 "product_id": self._top3_of_first_customer()[0],
                 "amount": 50000.0, "created_at": datetime(2026, 4, 20, 9, 30)},
            ]
        )
        mock_db.return_value = connection
        event = create_responded_event(
            customer_id=self.customer_id,
            product_id=self._top3_of_first_customer()[0],
            buy_date=date(2026, 4, 20),
            amount=50000.0,
        )
        self.assertEqual(event["event_type"], "responded")
        self.assertIn("attribution", event)
        self.assertIn("命中 Top3", event["attribution"])

    @patch("src.campaign.database_connection")
    def test_simulated_holding_drives_response_kpi(self, mock_db):
        product_id = self._top3_of_first_customer()[0]
        connection, cursor = fake_connection(
            [
                {"sent_count": 1, "responded_count": 0},
                {"campaign_event_id": 3, "strategy_id": self.strategy_id,
                 "event_type": "responded",
                 "occurred_at": datetime(2026, 4, 15, 10, 0),
                 "product_id": product_id, "amount": 50000.0,
                 "created_at": datetime(2026, 4, 15, 10, 0)},
                {"holding_id": "SIM1", "customer_id": self.customer_id,
                 "product_id": product_id, "amount": 50000.0,
                 "buy_date": date(2026, 4, 15),
                 "attributed_strategy_id": self.strategy_id,
                 "created_at": datetime(2026, 4, 15, 10, 0)},
            ]
        )
        mock_db.return_value = connection

        result = simulate_holding_purchase(
            customer_id=self.customer_id,
            product_id=product_id,
            buy_date=date(2026, 4, 15),
            amount=50000.0,
        )

        self.assertTrue(result["demo"])
        self.assertEqual(result["kpi_delta"]["responded"], 1)
        self.assertEqual(result["event"]["event_type"], "responded")
        self.assertEqual(result["holding"]["customer_id"], self.customer_id)
        self.assertTrue(
            any("INSERT INTO app_demo_holding" in sql for sql in cursor.statements)
        )
        self.assertTrue(connection.commit.called)

    @patch("src.campaign.database_connection")
    def test_simulated_holding_requires_sent_event(self, mock_db):
        connection, cursor = fake_connection(
            [{"sent_count": 0, "responded_count": 0}]
        )
        mock_db.return_value = connection

        with self.assertRaisesRegex(CampaignInputError, "先标记已触达"):
            simulate_holding_purchase(
                customer_id=self.customer_id,
                product_id=self._top3_of_first_customer()[0],
                buy_date=date(2026, 4, 15),
            )

        self.assertFalse(
            any("INSERT INTO app_demo_holding" in sql for sql in cursor.statements)
        )
        self.assertTrue(connection.rollback.called)

    @patch("src.campaign.database_connection")
    def test_simulated_holding_rejects_future_purchase(self, mock_db):
        with self.assertRaisesRegex(CampaignInputError, "未来购买不能进入当前快照"):
            simulate_holding_purchase(
                customer_id=self.customer_id,
                product_id=self._top3_of_first_customer()[0],
                buy_date=date(2026, 4, 16),
                business_date=date(2026, 4, 15),
            )
        mock_db.assert_not_called()

    @patch("src.campaign.database_connection")
    def test_simulated_holding_does_not_increment_twice(self, mock_db):
        connection, cursor = fake_connection(
            [{"sent_count": 1, "responded_count": 1}]
        )
        mock_db.return_value = connection

        with self.assertRaisesRegex(CampaignInputError, "不会再次增加 KPI"):
            simulate_holding_purchase(
                customer_id=self.customer_id,
                product_id=self._top3_of_first_customer()[0],
                buy_date=date(2026, 4, 15),
            )

        self.assertFalse(
            any("INSERT INTO app_demo_holding" in sql for sql in cursor.statements)
        )
        self.assertTrue(connection.rollback.called)


if __name__ == "__main__":
    unittest.main()
