from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import pymysql

from ..db import get_connection
from ..errors import ServiceError
from ..risk import RISK_LABELS


ZERO = Decimal("0")
RISK_LEVELS = ("R1", "R2", "R3", "R4", "R5")
PRODUCT_TYPES = ("现金管理", "固定期限", "定开", "混合")


def _decimal(value: object) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _ratio(value: Decimal, total: Decimal) -> float | None:
    if total == 0:
        return None
    return float((value / total).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def build_risk_distribution(rows: list[dict]) -> list[dict]:
    counts = {row["risk_appetite"]: int(row["customer_count"]) for row in rows}
    return [
        {
            "risk_level": level,
            "risk_label": RISK_LABELS[level],
            "count": counts.get(level, 0),
        }
        for level in RISK_LEVELS
    ]


def build_holding_distribution(
    rows: list[dict], total_holding_amount: Decimal
) -> list[dict]:
    amounts = {
        row["product_type"]: _decimal(row["holding_amount"])
        for row in rows
    }
    ordered_types = [*PRODUCT_TYPES]
    ordered_types.extend(sorted(set(amounts) - set(PRODUCT_TYPES)))
    return [
        {
            "product_type": product_type,
            "holding_amount": float(amounts.get(product_type, ZERO)),
            "ratio": _ratio(amounts.get(product_type, ZERO), total_holding_amount),
        }
        for product_type in ordered_types
    ]


def _a1_placeholder() -> dict:
    return {
        "status": "NOT_READY",
        "metric_scope": "OFFLINE_VALIDATION",
        "auc": None,
        "f1": None,
        "lift_at_10": None,
        "probability_distribution": [],
    }


def _a2_placeholder() -> dict:
    return {
        "status": "NOT_READY",
        "metric_scope": "OFFLINE_VALIDATION",
        "target_customer_count": None,
        "generated_customer_count": None,
        "coverage_rate": None,
        "hit_rate_at_3": None,
        "channel_distribution": [],
    }


def _portfolio_placeholder(scenario_id: str | None = None) -> dict:
    return {
        "status": "NOT_READY",
        "scenario_id": scenario_id,
        "total_amount": None,
        "expected_return": None,
        "volatility": None,
        "utility": None,
        "cash_weight": None,
        "constraints_satisfied": None,
        "allocation_by_product_type": [],
        "allocation_items": [],
    }


def _marketing_funnel_placeholder() -> dict:
    return {
        "status": "NOT_READY",
        "target_customer_count": None,
        "generated_customer_count": None,
        "contacted_customer_count": None,
        "responded_customer_count": None,
    }


def get_dashboard_overview(*, scenario_id: str | None = None) -> dict:
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM t_customer) AS customer_count,
                        (SELECT COALESCE(SUM(aum), 0) FROM t_customer) AS total_aum,
                        (SELECT COUNT(*) FROM t_product) AS product_count,
                        (SELECT COALESCE(SUM(amount), 0) FROM t_holding)
                            AS total_holding_amount
                    """
                )
                metrics = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT risk_appetite, COUNT(*) AS customer_count
                    FROM t_customer
                    GROUP BY risk_appetite
                    """
                )
                risk_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT p.product_type, COALESCE(SUM(h.amount), 0) AS holding_amount
                    FROM t_holding h
                    JOIN t_product p ON p.product_id = h.product_id
                    GROUP BY p.product_type
                    """
                )
                holding_rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError, TypeError) as exc:
        raise ServiceError("unable to query dashboard overview") from exc

    total_aum = _decimal(metrics["total_aum"])
    total_holding_amount = _decimal(metrics["total_holding_amount"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "business_metrics": {
            "customer_count": int(metrics["customer_count"]),
            "total_aum": float(total_aum),
            "product_count": int(metrics["product_count"]),
            "total_holding_amount": float(total_holding_amount),
            "currency": "CNY",
            "historical_contact_count": None,
            "historical_response_rate": None,
            "marketing_status": "NOT_READY",
        },
        "risk_distribution": build_risk_distribution(risk_rows),
        "holding_distribution": build_holding_distribution(
            holding_rows, total_holding_amount
        ),
        "a1_performance": _a1_placeholder(),
        "a2_performance": _a2_placeholder(),
        "portfolio": _portfolio_placeholder(scenario_id),
        "marketing_funnel": _marketing_funnel_placeholder(),
    }


def get_dashboard_portfolio(scenario_id: str) -> dict:
    return _portfolio_placeholder(scenario_id)
