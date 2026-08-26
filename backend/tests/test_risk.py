import unittest

from backend.app.risk import assess_risk


class RiskRuleTestCase(unittest.TestCase):
    def test_maps_new_customer_to_expected_level(self):
        level = assess_risk(
            {
                "age_group": "35-44",
                "income_level": "30-50万",
                "occupation": "企业职员",
                "aum": 650000,
            }
        )
        self.assertEqual(level, "R4")

    def test_lower_capacity_customer_is_conservative(self):
        level = assess_risk(
            {
                "age_group": "65+",
                "income_level": "10万以下",
                "occupation": "退休",
                "aum": 50000,
            }
        )
        self.assertEqual(level, "R1")


if __name__ == "__main__":
    unittest.main()
