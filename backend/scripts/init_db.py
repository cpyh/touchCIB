from pathlib import Path

from backend.app.db import get_connection


SCHEMA_FILE = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"


def main() -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    connection = get_connection(database=False, autocommit=True)
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
    finally:
        connection.close()
    print("MySQL schema initialized: touch_cib")


if __name__ == "__main__":
    main()
