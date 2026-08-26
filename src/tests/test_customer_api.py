import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from src.app import app
from src.customer_api import (
    ValidationError,
    assess_risk,
    risk_label,
    validate_customer_create,
)

VALID_PAYLOAD = {
    "age_group": "35-44",
    "city": "上海",
    "occupation": "企业职员",
    "income_level": "30-50万",
    "register_date": "2026-04-01",
    "aum": 650000,
    "vip_level": "金卡",
    "has_app": True,
}


class RiskAssessmentTestCase(unittest.TestCase):
    def test_balanced_profile_maps_to_r4(self):
        self.assertEqual(
            assess_risk(
                {
                    "age_group": "35-44",
                    "income_level": "30-50万",
                    "occupation": "企业职员",
                    "aum": 650000,
                }
            ),
            "R4",
        )

    def test_conservative_profile_maps_to_r1(self):
        self.assertEqual(
            assess_risk(
                {
                    "age_group": "65+",
                    "income_level": "10万以下",
                    "occupation": "退休",
                    "aum": 50000,
                }
            ),
            "R1",
        )

    def test_risk_labels(self):
        self.assertEqual(risk_label("R1"), "谨慎型")
        self.assertEqual(risk_label("R5"), "进取型")


class CustomerValidationTestCase(unittest.TestCase):
    def test_valid_payload(self):
        payload = validate_customer_create(VALID_PAYLOAD)
        self.assertEqual(payload["aum"], Decimal("650000"))
        self.assertIs(payload["has_app"], True)

    def test_negative_aum_rejected(self):
        with self.assertRaises(ValidationError):
            validate_customer_create({**VALID_PAYLOAD, "aum": -1})

    def test_unknown_age_group_rejected(self):
        with self.assertRaises(ValidationError):
            validate_customer_create({**VALID_PAYLOAD, "age_group": "90-100"})

    def test_future_register_date_rejected(self):
        with self.assertRaises(ValidationError):
            validate_customer_create(
                {**VALID_PAYLOAD, "register_date": (date.today() + timedelta(days=1)).isoformat()}
            )

    def test_has_app_must_be_boolean(self):
        with self.assertRaises(ValidationError):
            validate_customer_create({**VALID_PAYLOAD, "has_app": 1})


class CustomerApiRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("src.customer_api.list_customers")
    def test_list_customers_envelope(self, mock_list):
        mock_list.return_value = {
            "items": [], "total": 0, "page": 1, "page_size": 20,
        }
        response = self.client.get("/api/v1/customers")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["total"], 0)

    @patch("src.customer_api.create_customer")
    def test_create_customer_envelope(self, mock_create):
        mock_create.return_value = {"customer_id": "C1", "risk_appetite": "R3"}
        response = self.client.post("/api/v1/customers", json={"demo": True})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["data"]["customer_id"], "C1")

    def test_list_customers_invalid_page(self):
        response = self.client.get("/api/v1/customers?page=0")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], 400)


if __name__ == "__main__":
    unittest.main()
