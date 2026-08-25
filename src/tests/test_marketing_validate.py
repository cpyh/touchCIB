import tempfile
import unittest
from pathlib import Path

from src.marketing.validate import (
    validate_strategy_file,
    validate_strategy_rows,
)

VALID_ROWS = [
    {
        "customer_id": "C000001",
        "rank": "1",
        "product_id": "P001",
        "recommended_channel": "sms",
        "recommended_time": "工作日09:00-12:00",
        "marketing_script": "推荐产品一，理财非存款，产品有风险，投资须谨慎。",
    },
    {
        "customer_id": "C000001",
        "rank": "2",
        "product_id": "P002",
        "recommended_channel": "call",
        "recommended_time": "工作日18:00-21:00",
        "marketing_script": "推荐产品二，理财非存款，产品有风险，投资须谨慎。",
    },
    {
        "customer_id": "C000001",
        "rank": "3",
        "product_id": "P003",
        "recommended_channel": "manager",
        "recommended_time": "周末14:00-18:00",
        "marketing_script": "推荐产品三，理财非存款，产品有风险，投资须谨慎。",
    },
]


class MarketingValidateTestCase(unittest.TestCase):
    def test_valid_rows_pass(self):
        self.assertEqual(validate_strategy_rows(VALID_ROWS), [])

    def test_invalid_rank(self):
        rows = [{**VALID_ROWS[0], "rank": "4"}, *VALID_ROWS[1:]]
        self.assertTrue(validate_strategy_rows(rows))

    def test_row_count_not_three(self):
        errors = validate_strategy_rows(VALID_ROWS[:2])
        self.assertTrue(any("恰好 3 行" in error for error in errors))

    def test_duplicate_rank(self):
        rows = [
            {**VALID_ROWS[0]},
            {**VALID_ROWS[1], "rank": "1"},
            {**VALID_ROWS[2]},
        ]
        self.assertTrue(validate_strategy_rows(rows))

    def test_duplicate_product(self):
        rows = [
            {**VALID_ROWS[0]},
            {**VALID_ROWS[1], "product_id": "P001"},
            {**VALID_ROWS[2]},
        ]
        self.assertTrue(validate_strategy_rows(rows))

    def test_bad_channel(self):
        rows = [{**VALID_ROWS[0], "recommended_channel": "wechat"}, *VALID_ROWS[1:]]
        self.assertTrue(validate_strategy_rows(rows))

    def test_bad_time_slot(self):
        rows = [{**VALID_ROWS[0], "recommended_time": "深夜00:00-06:00"}, *VALID_ROWS[1:]]
        self.assertTrue(validate_strategy_rows(rows))

    def test_script_too_short_and_too_long(self):
        short = [{**VALID_ROWS[0], "marketing_script": "太短"}, *VALID_ROWS[1:]]
        self.assertTrue(validate_strategy_rows(short))
        long_script = "话术" * 151
        long_rows = [{**VALID_ROWS[0], "marketing_script": long_script}, *VALID_ROWS[1:]]
        self.assertTrue(validate_strategy_rows(long_rows))

    def test_empty_customer_id(self):
        rows = [{**VALID_ROWS[0], "customer_id": ""}, *VALID_ROWS[1:]]
        self.assertTrue(validate_strategy_rows(rows))

    def test_file_validation_columns_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partA_strategy.csv"
            with path.open("w", encoding="utf-8", newline="") as file:
                import csv

                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "customer_id", "rank", "product_id",
                        "recommended_channel", "recommended_time",
                        "marketing_script",
                    ],
                )
                writer.writeheader()
                writer.writerows(VALID_ROWS)

            errors = validate_strategy_file(
                path, expected_customers={"C000001"}
            )
            self.assertEqual(errors, [])

            missing = validate_strategy_file(
                path, expected_customers={"C000001", "C999999"}
            )
            self.assertTrue(any("缺少客户" in error for error in missing))

            bad_path = Path(directory) / "bad.csv"
            bad_path.write_text(
                "a,b,c,d,e,f\nC1,1,P1,sms,工作日09:00-12:00,话术内容十字符以上",
                encoding="utf-8",
            )
            bad = validate_strategy_file(bad_path)
            self.assertTrue(any("列名不符" in error for error in bad))


if __name__ == "__main__":
    unittest.main()
