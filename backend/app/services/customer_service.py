from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal

import pymysql

from ..db import get_connection, transaction
from ..errors import ServiceError, ValidationError
from ..risk import assess_risk, risk_label
from ..validation import RISK_LEVELS, VIP_LEVELS, validate_customer_create


def _customer_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"C{timestamp}{secrets.randbelow(100000):05d}"


def customer_dict(row: dict) -> dict:
    return {
        "customer_id": row["customer_id"],
        "age_group": row["age_group"],
        "city": row["city"],
        "occupation": row["occupation"],
        "income_level": row["income_level"],
        "register_date": row["register_date"].isoformat(),
        "aum": float(row["aum"]),
        "risk_appetite": row["risk_appetite"],
        "risk_label": risk_label(row["risk_appetite"]),
        "vip_level": row["vip_level"],
        "has_app": bool(row["has_app"]),
    }


def list_customers(
    *,
    page: int,
    page_size: int,
    keyword: str | None,
    risk_appetite: str | None,
    vip_level: str | None,
    city: str | None,
) -> dict:
    if not isinstance(page, int) or page < 1:
        raise ValidationError("page must be greater than or equal to 1")
    if not isinstance(page_size, int) or page_size < 1 or page_size > 100:
        raise ValidationError("page_size must be between 1 and 100")
    if risk_appetite and risk_appetite not in RISK_LEVELS:
        raise ValidationError("invalid risk_appetite")
    if vip_level and vip_level not in VIP_LEVELS:
        raise ValidationError("invalid vip_level")

    clauses: list[str] = []
    params: list[object] = []
    if keyword:
        clauses.append("(customer_id LIKE %s OR city LIKE %s OR occupation LIKE %s)")
        search = f"%{keyword.strip()}%"
        params.extend([search, search, search])
    if risk_appetite:
        clauses.append("risk_appetite = %s")
        params.append(risk_appetite)
    if vip_level:
        clauses.append("vip_level = %s")
        params.append(vip_level)
    if city:
        clauses.append("city = %s")
        params.append(city.strip())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS total FROM t_customer {where_sql}", params)
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"""
                    SELECT customer_id, age_group, city, occupation, income_level,
                           register_date, aum, risk_appetite, vip_level, has_app
                    FROM t_customer
                    {where_sql}
                    ORDER BY customer_id
                    LIMIT %s OFFSET %s
                    """,
                    [*params, page_size, offset],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query customers") from exc

    return {
        "items": [customer_dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_customer(raw_payload: object) -> dict:
    payload = validate_customer_create(raw_payload)
    risk_appetite = assess_risk(payload)

    for _ in range(3):
        customer_id = _customer_id()
        try:
            with transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO t_customer (
                            customer_id, age_group, city, occupation, income_level,
                            register_date, aum, risk_appetite, vip_level, has_app
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            customer_id,
                            payload["age_group"],
                            payload["city"],
                            payload["occupation"],
                            payload["income_level"],
                            payload["register_date"],
                            payload["aum"],
                            risk_appetite,
                            payload["vip_level"],
                            payload["has_app"],
                        ),
                    )
            row = {"customer_id": customer_id, **payload, "risk_appetite": risk_appetite}
            return customer_dict(row)
        except pymysql.err.IntegrityError as exc:
            if exc.args and exc.args[0] == 1062:
                continue
            raise ServiceError("unable to create customer") from exc
        except (pymysql.MySQLError, OSError, ValueError) as exc:
            raise ServiceError("unable to create customer") from exc

    raise ServiceError("unable to generate a unique customer id")
