from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import pymysql

from ..ai_analysis import parse_cached_analysis
from ..config import settings
from ..db import get_connection
from ..errors import NotFoundError, ServiceError
from ..risk import risk_label
from .customer_service import customer_dict


ZERO = Decimal("0")


def _ratio(value: Decimal, total: Decimal) -> float | None:
    if total == 0:
        return None
    return float((value / total).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _distribution(amounts: dict[str, Decimal], total: Decimal) -> list[dict]:
    return [
        {"name": name, "amount": float(amount), "ratio": _ratio(amount, total)}
        for name, amount in sorted(amounts.items())
    ]


def build_asset_profile(customer: dict, rows: list[dict]) -> dict:
    total = sum((row["amount"] for row in rows), ZERO)
    type_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    risk_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    liquid_amount = ZERO
    weighted_return = ZERO

    holdings = []
    for row in rows:
        amount = row["amount"]
        type_amounts[row["product_type"]] += amount
        risk_amounts[row["risk_level"]] += amount
        if row["liquidity"] in {"T+0", "T+1"}:
            liquid_amount += amount
        weighted_return += amount * row["expected_return"]
        holdings.append(
            {
                "holding_id": row["holding_id"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "product_type": row["product_type"],
                "risk_level": row["risk_level"],
                "liquidity": row["liquidity"],
                "amount": float(amount),
                "buy_date": row["buy_date"].isoformat(),
                "expected_return": float(row["expected_return"]),
            }
        )

    return {
        "aum": float(customer["aum"]),
        "holding_amount": float(total),
        "holding_product_count": len({row["product_id"] for row in rows}),
        "product_type_distribution": _distribution(type_amounts, total),
        "risk_distribution": _distribution(risk_amounts, total),
        "high_liquidity_ratio": _ratio(liquid_amount, total),
        "weighted_expected_return": _ratio(weighted_return, total),
        "holdings": holdings,
    }


def build_behavior_profile(
    customer: dict, events: list[dict], asset_profile: dict, as_of_date
) -> dict:
    total_counts = Counter(event["event_type"] for event in events)
    recent_start = as_of_date - timedelta(days=29)
    recent_counts = Counter(
        event["event_type"] for event in events if event["event_date"] >= recent_start
    )
    latest = max(events, key=lambda event: event["event_date"]) if events else None

    tags: list[str] = []
    if customer["aum"] >= Decimal("1000000"):
        tags.append("高净值客户")
    if customer["risk_appetite"] in {"R1", "R2"}:
        tags.append("偏好稳健")
    if customer["has_app"]:
        tags.append("数字渠道客户")
    if (asset_profile["high_liquidity_ratio"] or 0) >= 0.5:
        tags.append("重视流动性")
    if sum(recent_counts.values()) >= 5:
        tags.append("近期活跃")
    if recent_counts["complaint"] > 0:
        tags.append("需要重点维护")

    return {
        "total_counts": {
            name: total_counts[name] for name in ("login", "consult", "complaint")
        },
        "recent_30d_counts": {
            name: recent_counts[name] for name in ("login", "consult", "complaint")
        },
        "latest_event_type": latest["event_type"] if latest else None,
        "latest_event_date": latest["event_date"].isoformat() if latest else None,
        "tags": tags,
    }


def get_customer_profile(customer_id: str) -> dict:
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM t_customer WHERE customer_id = %s", (customer_id,))
                customer = cursor.fetchone()
                if customer is None:
                    raise NotFoundError("customer not found")

                as_of_date = max(settings.profile_as_of_date, customer["register_date"])
                cursor.execute(
                    """
                    SELECT h.holding_id, h.product_id, h.amount, h.buy_date,
                           p.product_name, p.product_type, p.risk_level,
                           p.liquidity, p.expected_return
                    FROM t_holding h
                    JOIN t_product p ON p.product_id = h.product_id
                    WHERE h.customer_id = %s AND h.buy_date <= %s
                    ORDER BY h.amount DESC, h.holding_id
                    """,
                    (customer_id, as_of_date),
                )
                holdings = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT event_type, event_date
                    FROM t_event
                    WHERE customer_id = %s AND event_date <= %s
                    ORDER BY event_date DESC, event_id DESC
                    """,
                    (customer_id, as_of_date),
                )
                events = cursor.fetchall()
        finally:
            connection.close()
    except NotFoundError:
        raise
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query customer profile") from exc

    asset_profile = build_asset_profile(customer, holdings)
    behavior_profile = build_behavior_profile(
        customer, events, asset_profile, as_of_date
    )
    basic = customer_dict(customer)
    basic["risk_label"] = risk_label(customer["risk_appetite"])
    return {
        "as_of_date": as_of_date.isoformat(),
        "basic_info": basic,
        "asset_profile": asset_profile,
        "behavior_profile": behavior_profile,
        "ai_summary": parse_cached_analysis(customer.get("ai_summary")),
        "ai_summary_generated_at": (
            customer["ai_summary_generated_at"].isoformat()
            if customer.get("ai_summary_generated_at")
            else None
        ),
    }
