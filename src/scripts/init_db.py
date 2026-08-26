#!/usr/bin/env python3
"""Initialize MySQL and load the demo's ODS, reference, and preset data."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

try:
    import pymysql
    from dotenv import load_dotenv
    from pymysql.connections import Connection
except ImportError as exc:
    raise SystemExit("Missing project dependencies. Run: uv sync") from exc


PROJECT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_DIR / "src" / "data" / "raw"
SCHEMA_FILE = PROJECT_DIR / "src" / "sql" / "schema.sql"
DWD_FILE = PROJECT_DIR / "src" / "sql" / "dwd.sql"
WAREHOUSE_FILE = PROJECT_DIR / "src" / "sql" / "warehouse.sql"
DEFAULT_BATCH_ID = "student_pkg_20260331"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CORRELATION_FILE = DATA_DIR / "partB_corr_matrix.csv"
SCENARIO_FILE = DATA_DIR / "partB_scenarios.csv"


@dataclass(frozen=True)
class TableSpec:
    table_name: str
    csv_name: str
    columns: tuple[str, ...]
    converters: dict[str, Callable[[str], object]]


TABLES = (
    TableSpec(
        table_name="ods_customer",
        csv_name="t_customer.csv",
        columns=(
            "customer_id",
            "age_group",
            "city",
            "occupation",
            "income_level",
            "register_date",
            "aum",
            "risk_appetite",
            "vip_level",
            "has_app",
        ),
        converters={"has_app": int},
    ),
    TableSpec(
        table_name="ods_product",
        csv_name="t_product.csv",
        columns=(
            "product_id",
            "product_name",
            "product_type",
            "risk_level",
            "expected_return",
            "volatility",
            "min_invest",
            "duration_days",
            "liquidity",
            "launch_date",
        ),
        converters={"duration_days": int},
    ),
    TableSpec(
        table_name="ods_holding",
        csv_name="t_holding.csv",
        columns=("holding_id", "customer_id", "product_id", "amount", "buy_date"),
        converters={},
    ),
    TableSpec(
        table_name="ods_campaign",
        csv_name="t_campaign.csv",
        columns=(
            "contact_id",
            "customer_id",
            "product_id",
            "channel",
            "contact_date",
            "responded",
        ),
        converters={"responded": int},
    ),
    TableSpec(
        table_name="ods_event",
        csv_name="t_event.csv",
        columns=("event_id", "customer_id", "event_type", "event_date"),
        converters={},
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the configured MySQL database and load the ODS tables."
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Create the database and tables without importing CSV data.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2_000,
        help="Rows per executemany batch (default: 2000).",
    )
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
    return args


def load_environment() -> None:
    load_dotenv(PROJECT_DIR / ".env")


def required_env(name: str, *, allow_empty: bool = False) -> str:
    value = os.getenv(name)
    if value is None or (not allow_empty and value == ""):
        raise ValueError(f"Required environment variable is missing: {name}")
    return value


def database_name() -> str:
    name = required_env("DB_NAME")
    if not IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError(
            "DB_NAME must start with a letter or underscore and contain only "
            "letters, numbers, and underscores"
        )
    return name


def positive_int_env(name: str, default: str) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def connection_config(*, database: str | None = None) -> dict[str, object]:
    port = positive_int_env("DB_PORT", "3306")
    if port > 65_535:
        raise ValueError("DB_PORT must be between 1 and 65535")

    config: dict[str, object] = {
        "host": required_env("DB_HOST"),
        "port": port,
        "user": required_env("DB_USER"),
        "password": required_env("DB_PASSWORD", allow_empty=True),
        "charset": "utf8mb4",
        "connect_timeout": positive_int_env("DB_CONNECT_TIMEOUT", "10"),
    }
    if database is not None:
        config["database"] = database
    return config


def connect(*, database: str | None = None, autocommit: bool = False) -> Connection:
    return pymysql.connect(
        **connection_config(database=database),
        autocommit=autocommit,
    )


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    return f"`{identifier}`"


def sql_statements(sql_text: str) -> list[str]:
    without_comments = "\n".join(
        line for line in sql_text.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def initialize_schema(database: str) -> None:
    if not SCHEMA_FILE.is_file():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_FILE}")

    connection = connect(autocommit=True)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS {quote_identifier(database)} "
                "DEFAULT CHARACTER SET utf8mb4 "
                "DEFAULT COLLATE utf8mb4_unicode_ci"
            )
            connection.select_db(database)
            for statement in sql_statements(SCHEMA_FILE.read_text(encoding="utf-8")):
                cursor.execute(statement)
        finally:
            cursor.close()
    finally:
        connection.close()


def rebuild_customer_360(database: str) -> None:
    if not WAREHOUSE_FILE.is_file():
        raise FileNotFoundError(f"Warehouse file not found: {WAREHOUSE_FILE}")

    connection = connect(database=database, autocommit=True)
    try:
        cursor = connection.cursor()
        try:
            for statement in sql_statements(WAREHOUSE_FILE.read_text(encoding="utf-8")):
                cursor.execute(statement)
        finally:
            cursor.close()
    finally:
        connection.close()


def rebuild_dwd(database: str) -> None:
    if not DWD_FILE.is_file():
        raise FileNotFoundError(f"DWD file not found: {DWD_FILE}")

    connection = connect(database=database)
    try:
        cursor = connection.cursor()
        try:
            for statement in sql_statements(DWD_FILE.read_text(encoding="utf-8")):
                cursor.execute(statement)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()


def upsert_sql(spec: TableSpec) -> str:
    insert_columns = (*spec.columns, "etl_batch_id")
    column_sql = ", ".join(quote_identifier(column) for column in insert_columns)
    placeholders = ", ".join(["%s"] * len(insert_columns))
    update_sql = ", ".join(
        [
            *(
                f"{quote_identifier(column)}=new.{quote_identifier(column)}"
                for column in spec.columns[1:]
            ),
            "`etl_batch_id`=new.`etl_batch_id`",
            "`loaded_at`=CURRENT_TIMESTAMP",
        ]
    )
    return (
        f"INSERT INTO {quote_identifier(spec.table_name)} ({column_sql}) "
        f"VALUES ({placeholders}) AS new "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )


def row_values(
    spec: TableSpec,
    row: Mapping[str, str | None],
    batch_id: str,
) -> tuple[object, ...]:
    values: list[object] = []
    for column in spec.columns:
        value = row.get(column)
        if value is None or value == "":
            raise ValueError(f"{spec.csv_name} contains an empty {column}")
        converter = spec.converters.get(column)
        values.append(converter(value) if converter else value)
    values.append(batch_id)
    return tuple(values)


def validate_headers(spec: TableSpec, fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise ValueError(f"{spec.csv_name} has no CSV header")

    actual = set(fieldnames)
    expected = set(spec.columns)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(
            f"{spec.csv_name} is missing columns: {', '.join(sorted(missing))}"
        )
    if unexpected:
        raise ValueError(
            f"{spec.csv_name} contains unexpected columns: "
            f"{', '.join(sorted(unexpected))}"
        )


def load_table(
    connection: Connection,
    spec: TableSpec,
    *,
    batch_id: str,
    batch_size: int,
) -> int:
    csv_path = DATA_DIR / spec.csv_name
    if not csv_path.is_file():
        raise FileNotFoundError(f"Source file not found: {csv_path}")

    cursor = connection.cursor()
    imported = 0
    batch: list[tuple[object, ...]] = []
    seen_primary_keys: set[str] = set()
    statement = upsert_sql(spec)

    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            validate_headers(spec, reader.fieldnames)

            primary_key = spec.columns[0]
            for row in reader:
                key = row.get(primary_key)
                if key in seen_primary_keys:
                    raise ValueError(
                        f"{spec.csv_name} contains duplicate {primary_key}: {key}"
                    )
                if key is not None:
                    seen_primary_keys.add(key)

                batch.append(row_values(spec, row, batch_id))
                if len(batch) >= batch_size:
                    cursor.executemany(statement, batch)
                    imported += len(batch)
                    batch.clear()

            if batch:
                cursor.executemany(statement, batch)
                imported += len(batch)

        return imported
    finally:
        cursor.close()


def correlation_rows(batch_id: str) -> list[tuple[object, ...]]:
    if not CORRELATION_FILE.is_file():
        raise FileNotFoundError(f"Source file not found: {CORRELATION_FILE}")

    with CORRELATION_FILE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
    if len(rows) < 2 or not rows[0] or rows[0][0] != "product_id":
        raise ValueError(f"Invalid correlation matrix: {CORRELATION_FILE}")

    column_ids = rows[0][1:]
    row_ids = [row[0] for row in rows[1:]]
    if not column_ids or row_ids != column_ids:
        raise ValueError("Correlation matrix row and column product IDs must match")

    values: list[tuple[object, ...]] = []
    for row in rows[1:]:
        if len(row) != len(column_ids) + 1:
            raise ValueError("Correlation matrix must be square")
        for related_product_id, raw_value in zip(column_ids, row[1:]):
            correlation = float(raw_value)
            if not -1 <= correlation <= 1:
                raise ValueError("Correlation values must be between -1 and 1")
            values.append((row[0], related_product_id, correlation, batch_id))
    return values


def load_product_correlations(connection: Connection, batch_id: str) -> int:
    rows = correlation_rows(batch_id)
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM ref_product_correlation")
        cursor.executemany(
            "INSERT INTO ref_product_correlation "
            "(product_id, related_product_id, correlation, etl_batch_id) "
            "VALUES (%s, %s, %s, %s)",
            rows,
        )
    finally:
        cursor.close()
    return len(rows)


def preset_scenario_rows() -> list[tuple[object, ...]]:
    if not SCENARIO_FILE.is_file():
        raise FileNotFoundError(f"Source file not found: {SCENARIO_FILE}")

    with SCENARIO_FILE.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        expected = {
            "scenario_id",
            "total_amount",
            "lambda",
            "max_single_weight",
            "max_high_risk_weight",
            "min_liquid_weight",
            "min_holdings",
        }
        if set(reader.fieldnames or []) != expected:
            raise ValueError(f"Invalid scenario columns: {SCENARIO_FILE}")

        rows = [
            (
                row["scenario_id"],
                f"官方场景 {row['scenario_id']}",
                float(row["total_amount"]),
                float(row["lambda"]),
                float(row["max_single_weight"]),
                float(row["max_high_risk_weight"]),
                float(row["min_liquid_weight"]),
                int(row["min_holdings"]),
            )
            for row in reader
        ]

    scenario_ids = [row[0] for row in rows]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("Preset scenario IDs must be unique")
    return rows


def load_preset_scenarios(connection: Connection) -> int:
    rows = preset_scenario_rows()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "DELETE FROM app_portfolio_scenario WHERE scenario_type = 'preset'"
        )
        cursor.executemany(
            "INSERT INTO app_portfolio_scenario "
            "(scenario_id, scenario_name, scenario_type, total_amount, "
            "risk_aversion, max_single_weight, max_high_risk_weight, "
            "min_liquid_weight, min_holdings) "
            "VALUES (%s, %s, 'preset', %s, %s, %s, %s, %s, %s)",
            rows,
        )
    finally:
        cursor.close()
    return len(rows)


def database_batch_row_count(
    connection: Connection,
    table_name: str,
    batch_id: str,
) -> int:
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(table_name)} "
            "WHERE `etl_batch_id`=%s",
            (batch_id,),
        )
        result = cursor.fetchone()
        if result is None:
            raise RuntimeError(f"Unable to count rows in {table_name}")
        return int(result[0])
    finally:
        cursor.close()


def main() -> int:
    load_environment()
    args = parse_args()
    database = database_name()
    batch_id = os.getenv("ETL_BATCH_ID", DEFAULT_BATCH_ID)
    if not batch_id:
        raise ValueError("ETL_BATCH_ID must not be empty")

    print(f"Initializing MySQL schema '{database}' from {SCHEMA_FILE}")
    initialize_schema(database)
    print(f"Database '{database}' schema is ready.")

    if args.schema_only:
        return 0

    connection = connect(database=database)
    results: list[tuple[str, int]] = []
    correlation_count = 0
    preset_count = 0
    try:
        for spec in TABLES:
            imported = load_table(
                connection,
                spec,
                batch_id=batch_id,
                batch_size=args.batch_size,
            )
            stored = database_batch_row_count(
                connection,
                spec.table_name,
                batch_id,
            )
            if stored != imported:
                raise RuntimeError(
                    f"Row count mismatch for {spec.table_name}: "
                    f"source={imported}, batch={stored}"
                )
            results.append((spec.table_name, imported))
        correlation_count = load_product_correlations(connection, batch_id)
        preset_count = load_preset_scenarios(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    for table_name, imported in results:
        print(f"[OK] {table_name}: imported={imported}")
    print(f"[OK] ref_product_correlation: imported={correlation_count}")
    print(f"[OK] app_portfolio_scenario: presets={preset_count}")
    rebuild_dwd(database)
    print("[OK] DWD dimensions and facts: rebuilt from ODS")
    rebuild_customer_360(database)
    print("[OK] dws_customer_360: rebuilt from DWD at 2026-03-31")
    print("ODS, DWD, and DWS initialization completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Database initialization failed: {exc}", file=sys.stderr)
        sys.exit(1)
