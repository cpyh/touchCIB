"""Read customer profiles from the demo warehouse table."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pymysql

from .database import database_connection
from .business_date import DEFAULT_BUSINESS_DATE


class CustomerProfileError(RuntimeError):
    """Raised when the customer profile cannot be queried."""


def json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def get_customer_profile(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict | None:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT customer_id, age_group, city, occupation, income_level, "
                    "register_date, aum, risk_appetite, vip_level, has_app, "
                    "%s AS snapshot_date FROM dwd_dim_customer "
                    "WHERE customer_id = %s AND register_date <= %s",
                    (business_date, customer_id, business_date),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CustomerProfileError("unable to query customer profile") from exc

    if row is None:
        return None
    return {key: json_value(value) for key, value in row.items()}
