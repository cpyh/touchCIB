"""Read and save portfolio scenario configurations."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pymysql

from .database import database_connection


SCENARIO_COLUMNS = """
    scenario_id, scenario_name, scenario_type, total_amount,
    risk_aversion, max_single_weight, max_high_risk_weight,
    min_liquid_weight, min_holdings, created_at, updated_at
"""


class ScenarioInputError(ValueError):
    """Raised when a custom scenario is invalid."""


class ScenarioStoreError(RuntimeError):
    """Raised when scenario data cannot be accessed."""


def json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def scenario_json(row: dict) -> dict:
    return {key: json_value(value) for key, value in row.items()}


def number_param(
    payload: dict,
    name: str,
    *,
    minimum: float,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioInputError(f"{name} must be a number")

    number = float(value)
    if not math.isfinite(number):
        raise ScenarioInputError(f"{name} must be finite")
    if minimum_inclusive and number < minimum:
        raise ScenarioInputError(f"{name} must be at least {minimum}")
    if not minimum_inclusive and number <= minimum:
        raise ScenarioInputError(f"{name} must be greater than {minimum}")
    if maximum is not None and number > maximum:
        raise ScenarioInputError(f"{name} must be at most {maximum}")
    return number


def scenario_values(payload: dict, *, max_holdings: int) -> dict[str, object]:
    name = payload.get("scenario_name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioInputError("scenario_name must be a non-empty string")
    if len(name.strip()) > 128:
        raise ScenarioInputError("scenario_name must be at most 128 characters")

    min_holdings = payload.get("min_holdings")
    if isinstance(min_holdings, bool) or not isinstance(min_holdings, int):
        raise ScenarioInputError("min_holdings must be an integer")
    if not 1 <= min_holdings <= max_holdings:
        raise ScenarioInputError(
            f"min_holdings must be between 1 and {max_holdings}"
        )

    return {
        "scenario_name": name.strip(),
        "total_amount": number_param(
            payload, "total_amount", minimum=0, minimum_inclusive=False
        ),
        "risk_aversion": number_param(payload, "risk_aversion", minimum=0),
        "max_single_weight": number_param(
            payload,
            "max_single_weight",
            minimum=0,
            maximum=1,
            minimum_inclusive=False,
        ),
        "max_high_risk_weight": number_param(
            payload, "max_high_risk_weight", minimum=0, maximum=1
        ),
        "min_liquid_weight": number_param(
            payload, "min_liquid_weight", minimum=0, maximum=1
        ),
        "min_holdings": min_holdings,
    }


def list_portfolio_scenarios() -> list[dict]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {SCENARIO_COLUMNS} FROM app_portfolio_scenario "
                    "ORDER BY scenario_type DESC, scenario_id"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ScenarioStoreError("unable to list portfolio scenarios") from exc
    return [scenario_json(row) for row in rows]


def create_portfolio_scenario(payload: dict) -> dict:
    try:
        connection = database_connection()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ScenarioStoreError("unable to save portfolio scenario") from exc

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS product_count FROM dwd_dim_product")
            product_count = int(cursor.fetchone()["product_count"])
            if product_count == 0:
                raise ScenarioStoreError("product data is empty")

            values = scenario_values(payload, max_holdings=product_count)
            scenario_id = f"CUSTOM_{uuid4().hex[:12].upper()}"
            cursor.execute(
                "INSERT INTO app_portfolio_scenario "
                "(scenario_id, scenario_name, scenario_type, total_amount, "
                "risk_aversion, max_single_weight, max_high_risk_weight, "
                "min_liquid_weight, min_holdings) "
                "VALUES (%s, %s, 'custom', %s, %s, %s, %s, %s, %s)",
                (
                    scenario_id,
                    values["scenario_name"],
                    values["total_amount"],
                    values["risk_aversion"],
                    values["max_single_weight"],
                    values["max_high_risk_weight"],
                    values["min_liquid_weight"],
                    values["min_holdings"],
                ),
            )
            cursor.execute(
                f"SELECT {SCENARIO_COLUMNS} FROM app_portfolio_scenario "
                "WHERE scenario_id = %s",
                (scenario_id,),
            )
            row = cursor.fetchone()
        connection.commit()
    except ScenarioInputError:
        connection.rollback()
        raise
    except ScenarioStoreError:
        connection.rollback()
        raise
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        connection.rollback()
        raise ScenarioStoreError("unable to save portfolio scenario") from exc
    finally:
        connection.close()

    if row is None:
        raise ScenarioStoreError("saved portfolio scenario was not found")
    return scenario_json(row)
