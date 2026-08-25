import unittest
from unittest.mock import patch

from src.app import app
from src.scenario import ScenarioInputError, scenario_values


VALID_SCENARIO = {
    "scenario_name": "稳健型",
    "total_amount": 500000,
    "risk_aversion": 0.94,
    "max_single_weight": 0.3,
    "max_high_risk_weight": 0.5,
    "min_liquid_weight": 0.2,
    "min_holdings": 4,
}


class ScenarioEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("src.app.list_portfolio_scenarios")
    def test_lists_scenarios(self, list_scenarios) -> None:
        list_scenarios.return_value = [
            {"scenario_id": "S01", "scenario_type": "preset"}
        ]

        response = self.client.get("/portfolio/scenarios")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["scenarios"][0]["scenario_id"], "S01")

    @patch("src.app.create_portfolio_scenario")
    def test_saves_custom_scenario(self, create_scenario) -> None:
        create_scenario.return_value = {
            "scenario_id": "CUSTOM_123",
            "scenario_name": "稳健型",
            "scenario_type": "custom",
        }

        response = self.client.post("/portfolio/scenarios", json=VALID_SCENARIO)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["scenario_type"], "custom")

    def test_rejects_too_many_holdings(self) -> None:
        payload = {**VALID_SCENARIO, "min_holdings": 31}

        with self.assertRaises(ScenarioInputError):
            scenario_values(payload, max_holdings=30)


if __name__ == "__main__":
    unittest.main()
