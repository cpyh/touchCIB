import unittest
from datetime import date
from unittest.mock import MagicMock

from src.portfolio_batch import compute_portfolio_batch, persist_portfolio_batch


class PortfolioBatchTestCase(unittest.TestCase):
    def test_compute_and_persist_are_ads_shaped_and_idempotent(self):
        scenario = {
            "scenario_id": "S01",
            "total_amount": 500_000,
            "risk_aversion": 1.0,
            "max_single_weight": 0.6,
            "max_high_risk_weight": 0.4,
            "min_liquid_weight": 0.2,
            "min_holdings": 2,
        }

        def optimizer(_payload):
            return {
                "summary": {
                    "utility": 0.03,
                    "expected_return": 0.05,
                    "portfolio_volatility": 0.02,
                    "invested_weight": 1.0,
                    "cash_weight": 0.0,
                    "holdings_count": 2,
                    "high_risk_weight": 0.2,
                    "liquid_plus_cash": 0.5,
                    "optimality_gap": 0.0,
                },
                "allocations": [
                    {"product_id": "P001", "weight": 0.6, "amount": 300_000},
                    {"product_id": "P002", "weight": 0.4, "amount": 200_000},
                ],
            }

        result = compute_portfolio_batch(
            date(2026, 4, 15),
            [scenario],
            batch_id="portfolio_test",
            optimizer=optimizer,
        )
        self.assertEqual(len(result.result_rows), 1)
        self.assertEqual(result.result_rows[0][11], 1)
        self.assertEqual(len(result.allocation_rows), 2)

        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        persist_portfolio_batch(result, connection_factory=lambda: connection)
        delete_statements = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if call.args and str(call.args[0]).startswith("DELETE")
        ]
        self.assertEqual(len(delete_statements), 2)
        self.assertEqual(cursor.executemany.call_count, 2)
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
