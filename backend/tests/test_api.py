import unittest
from unittest.mock import patch

from backend.app import create_app


class CustomerApiTestCase(unittest.TestCase):
    def setUp(self):
        self.client = create_app(testing=True).test_client()

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    @patch("backend.app.routes.customers.list_customers")
    def test_list_customers(self, list_customers):
        list_customers.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
        response = self.client.get("/api/v1/customers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["total"], 0)

    @patch("backend.app.routes.customers.create_customer")
    def test_create_customer(self, create_customer):
        create_customer.return_value = {"customer_id": "C1", "risk_appetite": "R3"}
        response = self.client.post("/api/v1/customers", json={"demo": True})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["data"]["customer_id"], "C1")


if __name__ == "__main__":
    unittest.main()
