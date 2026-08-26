import os
import unittest
from unittest.mock import patch

from src.scripts import init_db


class InitDatabaseTestCase(unittest.TestCase):
    def valid_environment(self) -> dict[str, str]:
        return {
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "3306",
            "DB_USER": "test_user",
            "DB_PASSWORD": "test_password",
            "DB_NAME": "cib_test",
            "DB_CONNECT_TIMEOUT": "5",
        }

    def test_connection_config_uses_environment(self) -> None:
        with patch.dict(os.environ, self.valid_environment(), clear=True):
            config = init_db.connection_config(database=init_db.database_name())

        self.assertEqual(config["host"], "127.0.0.1")
        self.assertEqual(config["port"], 3306)
        self.assertEqual(config["user"], "test_user")
        self.assertEqual(config["password"], "test_password")
        self.assertEqual(config["database"], "cib_test")
        self.assertEqual(config["connect_timeout"], 5)

    def test_missing_database_user_fails_fast(self) -> None:
        environment = self.valid_environment()
        del environment["DB_USER"]

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "DB_USER"):
                init_db.connection_config()

    def test_unsafe_database_name_is_rejected(self) -> None:
        environment = self.valid_environment()
        environment["DB_NAME"] = "cib; DROP DATABASE cib"

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "DB_NAME"):
                init_db.database_name()

    def test_upsert_uses_mysql_row_alias(self) -> None:
        statement = init_db.upsert_sql(init_db.TABLES[0])

        self.assertIn("AS new ON DUPLICATE KEY UPDATE", statement)
        self.assertNotIn("VALUES(`", statement)

    def test_schema_contains_one_statement_per_table(self) -> None:
        statements = init_db.sql_statements(
            init_db.SCHEMA_FILE.read_text(encoding="utf-8")
        )

        self.assertEqual(len(statements), len(init_db.TABLES) + 9)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS ads_marketing_response_score",
            init_db.SCHEMA_FILE.read_text(encoding="utf-8"),
        )

    def test_dwd_rebuilds_dimensions_and_facts_from_ods(self) -> None:
        dwd_sql = init_db.DWD_FILE.read_text(encoding="utf-8")

        self.assertIn("INSERT INTO dwd_dim_customer", dwd_sql)
        self.assertIn("INSERT INTO dwd_dim_product", dwd_sql)
        self.assertIn("INSERT INTO dwd_fact_holding", dwd_sql)
        self.assertIn("INSERT INTO dwd_fact_campaign", dwd_sql)
        self.assertIn("INSERT INTO dwd_fact_event", dwd_sql)

    def test_reference_and_preset_source_shapes(self) -> None:
        self.assertEqual(
            len(init_db.correlation_rows("test_batch")),
            30 * 30,
        )
        self.assertEqual(len(init_db.preset_scenario_rows()), 20)

    def test_warehouse_builds_a_physical_table(self) -> None:
        warehouse_sql = init_db.WAREHOUSE_FILE.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE dws_customer_360", warehouse_sql)
        self.assertNotIn("CREATE OR REPLACE VIEW", warehouse_sql)
        self.assertIn("ADD PRIMARY KEY (customer_id)", warehouse_sql)
        self.assertIn("FROM dwd_dim_customer", warehouse_sql)
        self.assertIn("FROM dwd_fact_holding", warehouse_sql)
        self.assertIn("FROM dwd_fact_campaign", warehouse_sql)
        self.assertIn("FROM dwd_fact_event", warehouse_sql)
        self.assertIn("AS snapshot_date", warehouse_sql)

    def test_all_source_files_exist(self) -> None:
        for spec in init_db.TABLES:
            with self.subTest(csv_name=spec.csv_name):
                self.assertTrue((init_db.DATA_DIR / spec.csv_name).is_file())
        self.assertTrue(init_db.CORRELATION_FILE.is_file())
        self.assertTrue(init_db.SCENARIO_FILE.is_file())
        self.assertTrue(init_db.DWD_FILE.is_file())


if __name__ == "__main__":
    unittest.main()
