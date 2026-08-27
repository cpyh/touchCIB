"""ADS A1客户产品机会名单查询；Flask运行时不读取提交文件。"""

from __future__ import annotations

from datetime import date

import pymysql

from ..database import database_connection

SORT_ORDERS = ("prob_desc", "contact_id", "delta_desc")


def available_dates() -> list[dict]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT strategy_date FROM ads_a1_customer_product_score "
                    "ORDER BY strategy_date"
                )
                return [
                    {"date": row["strategy_date"].isoformat(), "scope": "warehouse_batch"}
                    for row in cursor.fetchall()
                ]
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise RuntimeError("unable to query A1 batch dates") from exc


def query_roster(
    *,
    page: int = 1,
    size: int = 50,
    channel: str | None = None,
    min_prob: float | None = None,
    sort: str = "prob_desc",
    keyword: str | None = None,
    contact_date: str | None = None,
) -> dict:
    if sort not in SORT_ORDERS:
        raise ValueError(f"sort must be one of {SORT_ORDERS}")
    if page < 1 or size < 1 or size > 200:
        raise ValueError("page >= 1, 1 <= size <= 200")
    if channel and channel not in ("sms", "call", "app_push", "manager"):
        raise ValueError(f"unknown channel: {channel}")
    if min_prob is not None and not 0 <= float(min_prob) <= 1:
        raise ValueError("min_prob must be in [0, 1]")

    dates = available_dates()
    if not dates:
        return {
            "total": 0,
            "page": page,
            "size": size,
            "contact_date": contact_date,
            "model_scope": "warehouse_batch",
            "dates": [],
            "rank_move_count": None,
            "customers": [],
        }
    effective_date = contact_date or dates[-1]["date"]
    if effective_date not in {item["date"] for item in dates}:
        raise ValueError(f"营销批次不存在：{effective_date}")
    try:
        date.fromisoformat(effective_date)
    except ValueError as exc:
        raise ValueError("contact_date must be YYYY-MM-DD") from exc

    conditions = ["a.strategy_date = %s"]
    params: list[object] = [effective_date]
    if channel:
        conditions.append("a.recommended_channel = %s")
        params.append(channel)
    if min_prob is not None:
        conditions.append("a.response_prob >= %s")
        params.append(float(min_prob))
    if keyword and keyword.strip():
        term = f"%{keyword.strip()}%"
        conditions.append(
            "(a.customer_id LIKE %s OR a.product_id LIKE %s OR p.product_name LIKE %s)"
        )
        params.extend([term, term, term])
    where = " AND ".join(conditions)
    order_by = (
        "a.response_prob DESC, a.customer_id, a.product_id"
        if sort == "prob_desc"
        else "a.customer_id, a.product_id"
        if sort == "contact_id"
        else "ABS(COALESCE(prev.a1_rank, a.a1_rank) - a.a1_rank) DESC, "
        "a.response_prob DESC"
    )
    previous_join = """
        LEFT JOIN ads_a1_customer_product_score prev
          ON prev.customer_id = a.customer_id
         AND prev.product_id = a.product_id
         AND prev.strategy_date = (
             SELECT MAX(strategy_date) FROM ads_a1_customer_product_score
             WHERE strategy_date < a.strategy_date
         )
    """
    statement = f"""
        SELECT a.customer_id, a.product_id, p.product_name, p.risk_level,
               a.recommended_channel AS channel, a.strategy_date,
               a.response_prob, a.a1_rank,
               d.rule_passed,
               (COALESCE(prev.a1_rank, a.a1_rank) - a.a1_rank) AS rank_delta
        FROM ads_a1_customer_product_score a
        JOIN dwd_dim_product p ON p.product_id = a.product_id
        LEFT JOIN ads_a2_candidate_decision d
          ON d.strategy_date = a.strategy_date
         AND d.customer_id = a.customer_id
         AND d.product_id = a.product_id
        {previous_join}
        WHERE {where}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """
    count_sql = f"""
        SELECT COUNT(*) AS count
        FROM ads_a1_customer_product_score a
        JOIN dwd_dim_product p ON p.product_id = a.product_id
        WHERE {where}
    """
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(count_sql, tuple(params))
                total = int(cursor.fetchone()["count"])
                cursor.execute(
                    statement,
                    (*params, size, (page - 1) * size),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise RuntimeError("unable to query A1 warehouse roster") from exc

    return {
        "total": total,
        "page": page,
        "size": size,
        "contact_date": effective_date,
        "model_scope": "warehouse_batch",
        "dates": dates,
        "rank_move_count": None,
        "customers": [
            {
                "contact_id": f"{row['strategy_date']:%Y%m%d}:{row['customer_id']}:{row['product_id']}",
                "customer_id": str(row["customer_id"]),
                "product_id": str(row["product_id"]),
                "product_name": str(row["product_name"]),
                "risk_level": str(row["risk_level"]),
                "channel": str(row["channel"]),
                "contact_date": row["strategy_date"].isoformat(),
                "response_prob": round(float(row["response_prob"]), 12),
                "strategy_eligible": bool(row["rule_passed"]),
                "rank": int(row["a1_rank"]),
                "rank_delta": int(row["rank_delta"] or 0),
            }
            for row in rows
        ],
    }


__all__ = ["available_dates", "query_roster"]
