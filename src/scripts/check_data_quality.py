#!/usr/bin/env python3
"""执行 MySQL 数据质量门禁；任一检查失败时返回非零退出码。"""

from __future__ import annotations

from pathlib import Path

from src.database import database_connection
from src.scripts.init_db import sql_statements


QUALITY_FILE = Path(__file__).resolve().parents[1] / "sql" / "quality_checks.sql"


def run_quality_checks() -> list[dict]:
    statements = sql_statements(QUALITY_FILE.read_text(encoding="utf-8"))
    connection = database_connection()
    rows: list[dict] = []
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                if statement.lstrip().upper().startswith("USE "):
                    continue
                cursor.execute(statement)
                if cursor.description:
                    rows = list(cursor.fetchall())
    finally:
        connection.close()
    return rows


def main() -> int:
    rows = run_quality_checks()
    failures = [row for row in rows if row["status"] != "PASS"]
    for row in rows:
        print(
            f"[{row['status']}] {row['category']} · {row['check_name']} "
            f"expected={row['expected_value']} actual={row['actual_value']}",
            flush=True,
        )
    print(
        f"quality_checks={len(rows)} passed={len(rows) - len(failures)} "
        f"failed={len(failures)}",
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
