"""客户经理营销机会队列：只读MySQL DWD/ADS与执行事件。"""

from __future__ import annotations

from datetime import date, timedelta

import pymysql

from ..business_date import DEFAULT_BUSINESS_DATE
from ..database import database_connection

STATUS_VALUES = ("all", "pending", "follow_up", "converted")
WORKSPACE_VALUES = ("all", "manager")
MANAGER_VIEW_VALUES = ("today", "pool")


class MarketingTaskStoreError(RuntimeError):
    """营销任务数据不可用。"""


def _event_statuses(cursor, business_date: date) -> dict[str, str]:
    cursor.execute(
        "SELECT SUBSTRING_INDEX(strategy_id, ':', 1) AS customer_id, "
        "MAX(event_type = 'sent') AS has_sent, "
        "MAX(event_type = 'responded') AS has_responded "
        "FROM app_campaign_event WHERE occurred_at < %s GROUP BY customer_id",
        (business_date + timedelta(days=1),),
    )
    statuses: dict[str, str] = {}
    for row in cursor.fetchall():
        status = (
            "converted"
            if int(row["has_responded"] or 0)
            else "follow_up"
            if int(row["has_sent"] or 0)
            else "pending"
        )
        statuses[str(row["customer_id"])] = status
    return statuses


def _latest_business_rows(
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> tuple[list[dict], str | None, int, int]:
    """返回指定业务日全部存量客户、机会和Top1。"""
    statement = """
        WITH opportunity AS (
            SELECT
                a.customer_id,
                a.product_id,
                a.recommended_channel,
                a.response_prob,
                a.strategy_date
            FROM ads_a1_customer_product_score a
            WHERE a.strategy_date = %s AND a.a1_rank = 1
        )
        SELECT
            c.customer_id, c.risk_appetite, c.vip_level, c.aum,
            s.strategy_id, s.product_id, sp.product_name, sp.risk_level,
            sp.expected_return, s.recommended_channel, s.recommended_time,
            s.strategy_date, s.a1_probability, s.a1_rank,
            o.product_id AS opportunity_product_id,
            op.product_name AS opportunity_product_name,
            o.recommended_channel AS opportunity_channel,
            o.response_prob,
            o.strategy_date AS opportunity_date
        FROM dwd_dim_customer c
        LEFT JOIN opportunity o
          ON o.customer_id = c.customer_id
        LEFT JOIN dwd_dim_product op ON op.product_id = o.product_id
        LEFT JOIN ads_marketing_strategy s
          ON s.customer_id = c.customer_id
         AND s.strategy_date = %s
         AND s.strategy_rank = 1
        LEFT JOIN dwd_dim_product sp ON sp.product_id = s.product_id
        WHERE c.register_date <= %s
    """
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    statement,
                    (business_date, business_date, business_date),
                )
                rows = list(cursor.fetchall())
                statuses = _event_statuses(cursor, business_date)
                cursor.execute(
                    "SELECT COUNT(DISTINCT customer_id) AS customers "
                    "FROM ads_marketing_strategy WHERE strategy_date=%s",
                    (business_date,),
                )
                strategy_summary = cursor.fetchone() or {}
                cursor.execute(
                    "SELECT COUNT(DISTINCT customer_id) AS customers "
                    "FROM ads_a1_customer_product_score "
                    "WHERE strategy_date = %s",
                    (business_date,),
                )
                score_summary = cursor.fetchone() or {}
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise MarketingTaskStoreError("unable to query marketing warehouse") from exc

    for row in rows:
        row["status"] = statuses.get(str(row["customer_id"]), "pending")
    return (
        rows,
        business_date.isoformat()
        if int(strategy_summary.get("customers") or 0) > 0
        else None,
        int(strategy_summary.get("customers") or 0),
        int(score_summary.get("customers") or 0),
    )


def _expiring_customers(
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> frozenset[str]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT h.customer_id
                    FROM dwd_fact_holding h
                    JOIN dwd_dim_product p ON p.product_id = h.product_id
                    WHERE p.duration_days > 0
                      AND DATE_ADD(h.buy_date, INTERVAL p.duration_days DAY) > %s
                      AND DATE_ADD(h.buy_date, INTERVAL p.duration_days DAY) <= %s
                    """,
                    (business_date, business_date + timedelta(days=30)),
                )
                return frozenset(str(row["customer_id"]) for row in cursor.fetchall())
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        return frozenset()


def query_marketing_tasks(
    *,
    page: int = 1,
    size: int = 20,
    status: str = "all",
    keyword: str | None = None,
    cohort: str = "all",
    workspace: str = "all",
    manager_view: str = "today",
    manager_daily_capacity: int = 12,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    if page < 1 or size < 1 or size > 100:
        raise ValueError("page >= 1, 1 <= size <= 100")
    if status not in STATUS_VALUES:
        raise ValueError(f"status must be one of {STATUS_VALUES}")
    if cohort not in ("all", "expiry"):
        raise ValueError("cohort must be 'all' or 'expiry'")
    if workspace not in WORKSPACE_VALUES:
        raise ValueError(f"workspace must be one of {WORKSPACE_VALUES}")
    if manager_view not in MANAGER_VIEW_VALUES:
        raise ValueError(f"manager_view must be one of {MANAGER_VIEW_VALUES}")
    if manager_daily_capacity < 1 or manager_daily_capacity > 100:
        raise ValueError("manager_daily_capacity must be between 1 and 100")

    rows, latest_date, strategy_ready_customers, model_covered_customers = (
        _latest_business_rows(business_date)
    )
    population_total = len(rows)
    if cohort == "expiry":
        expiring = _expiring_customers(business_date)
        rows = [row for row in rows if str(row["customer_id"]) in expiring]
    rows.sort(
        key=lambda row: (
            -(float(row["response_prob"]) if row["response_prob"] is not None else -1),
            str(row["customer_id"]),
        )
    )
    counts = {
        value: sum(row["status"] == value for row in rows)
        for value in STATUS_VALUES
        if value != "all"
    }
    counts["all"] = len(rows)

    manager_rows = [
        row for row in rows if row.get("recommended_channel") == "manager"
    ]
    manager_pending_rows = [
        row for row in manager_rows if row["status"] == "pending"
    ]
    manager_pool_rank = {
        str(row["customer_id"]): rank
        for rank, row in enumerate(manager_pending_rows, start=1)
    }
    manager_today_ids = {
        str(row["customer_id"])
        for row in manager_pending_rows[:manager_daily_capacity]
    }
    manager_summary = {
        "pool_total": len(manager_rows),
        "pending": len(manager_pending_rows),
        "today_count": min(len(manager_pending_rows), manager_daily_capacity),
        "follow_up": sum(row["status"] == "follow_up" for row in manager_rows),
        "converted": sum(row["status"] == "converted" for row in manager_rows),
        "daily_capacity": manager_daily_capacity,
    }

    if workspace == "manager":
        if status == "pending":
            rows = (
                manager_pending_rows[:manager_daily_capacity]
                if manager_view == "today"
                else manager_pending_rows
            )
        elif status == "all":
            rows = manager_rows
        else:
            rows = [row for row in manager_rows if row["status"] == status]
    elif status != "all":
        rows = [row for row in rows if row["status"] == status]
    if keyword and keyword.strip():
        term = keyword.strip().lower()
        rows = [
            row
            for row in rows
            if term in str(row["customer_id"]).lower()
            or term in str(row.get("product_id") or "").lower()
            or term in str(row.get("product_name") or "").lower()
            or term in str(row.get("opportunity_product_id") or "").lower()
            or term in str(row.get("opportunity_product_name") or "").lower()
        ]
    total = len(rows)
    page_rows = rows[(page - 1) * size : page * size]

    tasks = []
    for row in page_rows:
        ready = row.get("strategy_id") is not None
        probability = (
            float(row["response_prob"])
            if row.get("response_prob") is not None
            else None
        )
        tasks.append(
            {
                "customer_id": str(row["customer_id"]),
                "risk_appetite": str(row["risk_appetite"]),
                "vip_level": str(row["vip_level"]),
                "aum": round(float(row["aum"]), 2),
                "status": row["status"],
                "strategy_id": row.get("strategy_id"),
                "strategy_ready": ready,
                "strategy_source": "batch_generated" if ready else "batch_pending",
                "product_id": row.get("product_id"),
                "product_name": row.get("product_name"),
                "risk_level": row.get("risk_level"),
                "expected_return": (
                    round(float(row["expected_return"]), 6)
                    if row.get("expected_return") is not None
                    else None
                ),
                "recommended_channel": row.get("recommended_channel"),
                "recommended_time": row.get("recommended_time"),
                "response_prob": round(probability, 12) if probability is not None else None,
                "opportunity_score": round(probability, 12) if probability is not None else None,
                "opportunity_source": "ads_a1_batch" if probability is not None else "not_scored",
                "model_contact_id": None,
                "opportunity_product_id": row.get("opportunity_product_id"),
                "opportunity_product_name": row.get("opportunity_product_name"),
                "opportunity_channel": row.get("opportunity_channel"),
                "opportunity_date": (
                    row["opportunity_date"].isoformat()
                    if row.get("opportunity_date") is not None
                    else None
                ),
                "manager_pool": row.get("recommended_channel") == "manager",
                "manager_pool_rank": manager_pool_rank.get(
                    str(row["customer_id"])
                ),
                "manager_today": str(row["customer_id"]) in manager_today_ids,
            }
        )

    return {
        "total": total,
        "population_total": population_total,
        "page": page,
        "size": size,
        "cohort": cohort,
        "workspace": workspace,
        "manager_view": manager_view,
        "business_date": business_date.isoformat(),
        "latest_strategy_date": latest_date,
        "counts": counts,
        "manager_summary": manager_summary,
        "strategy_ready_customers": strategy_ready_customers,
        "model_covered_customers": model_covered_customers,
        "unscored_customers": population_total - model_covered_customers,
        "coverage_rate": (
            round(model_covered_customers / population_total, 6)
            if population_total
            else 0.0
        ),
        "tasks": tasks,
    }


__all__ = ["MarketingTaskStoreError", "query_marketing_tasks"]
