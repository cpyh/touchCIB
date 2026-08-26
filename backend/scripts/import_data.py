from __future__ import annotations

import argparse
import csv
from pathlib import Path

from backend.app.db import transaction


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "data" / "raw"


IMPORTS = (
    (
        "t_customer.csv",
        """
        INSERT INTO t_customer (
            customer_id, age_group, city, occupation, income_level,
            register_date, aum, risk_appetite, vip_level, has_app
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            age_group=VALUES(age_group), city=VALUES(city), occupation=VALUES(occupation),
            income_level=VALUES(income_level), register_date=VALUES(register_date),
            aum=VALUES(aum), risk_appetite=VALUES(risk_appetite),
            vip_level=VALUES(vip_level), has_app=VALUES(has_app)
        """,
        lambda row: (
            row["customer_id"], row["age_group"], row["city"], row["occupation"],
            row["income_level"], row["register_date"], row["aum"],
            row["risk_appetite"], row["vip_level"], int(row["has_app"]),
        ),
    ),
    (
        "t_product.csv",
        """
        INSERT INTO t_product (
            product_id, product_name, product_type, risk_level, expected_return,
            volatility, min_invest, duration_days, liquidity, launch_date
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            product_name=VALUES(product_name), product_type=VALUES(product_type),
            risk_level=VALUES(risk_level), expected_return=VALUES(expected_return),
            volatility=VALUES(volatility), min_invest=VALUES(min_invest),
            duration_days=VALUES(duration_days), liquidity=VALUES(liquidity),
            launch_date=VALUES(launch_date)
        """,
        lambda row: (
            row["product_id"], row["product_name"], row["product_type"],
            row["risk_level"], row["expected_return"], row["volatility"],
            row["min_invest"], int(row["duration_days"]), row["liquidity"],
            row["launch_date"],
        ),
    ),
    (
        "t_holding.csv",
        """
        INSERT INTO t_holding (holding_id, customer_id, product_id, amount, buy_date)
        VALUES (%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            customer_id=VALUES(customer_id), product_id=VALUES(product_id),
            amount=VALUES(amount), buy_date=VALUES(buy_date)
        """,
        lambda row: (
            row["holding_id"], row["customer_id"], row["product_id"],
            row["amount"], row["buy_date"],
        ),
    ),
    (
        "t_event.csv",
        """
        INSERT INTO t_event (event_id, customer_id, event_type, event_date)
        VALUES (%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            customer_id=VALUES(customer_id), event_type=VALUES(event_type),
            event_date=VALUES(event_date)
        """,
        lambda row: (
            row["event_id"], row["customer_id"], row["event_type"], row["event_date"],
        ),
    ),
)


def read_rows(path: Path, converter) -> list[tuple]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [converter(row) for row in csv.DictReader(file)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the four customer-profile CSV files")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    with transaction() as connection:
        with connection.cursor() as cursor:
            for file_name, sql, converter in IMPORTS:
                path = args.data_dir / file_name
                if not path.exists():
                    raise FileNotFoundError(path)
                rows = read_rows(path, converter)
                cursor.executemany(sql, rows)
                print(f"Imported {file_name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
