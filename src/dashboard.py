"""Tab4 看板聚合：KPI + 分布 + 漏斗。

设计（docs/demo-design.md §4）：
- KPI 目标配置在代码常量中（演示口径：固定经理 MGR001）；
- 客户、触达和营销策略均来自 DWD/ADS 与事件表；
- 数据分层行数来自 MySQL 各层 COUNT（DB 不可用时返回 None）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .business_date import DEFAULT_BUSINESS_DATE
from .dashboard_api import _a1_performance, _a2_performance, _portfolio_summary
from .database import database_connection

TOTAL_CUSTOMERS = 8000
DEMO_MANAGER_ID = "MGR001"

KPI_TARGETS = [
    {
        "kpi_id": "manager_conversion",
        "label": f"客户经理 {DEMO_MANAGER_ID} 4月转化数",
        "dimension": "manager",
        "scope": DEMO_MANAGER_ID,
        "period": "2026-04",
        "target": 30,
        "unit": "个",
    },
    {
        "kpi_id": "manager_response_rate",
        "label": "manager 渠道响应率",
        "dimension": "channel",
        "scope": "manager",
        "target": 0.25,
        "unit": "%",
    },
    {
        "kpi_id": "campaign_touch_progress",
        "label": "活动触达进度",
        "dimension": "campaign",
        "scope": "ALL",
        "target": 0.60,
        "unit": "%",
    },
]


def _strategy_frame(business_date: date = DEFAULT_BUSINESS_DATE) -> pd.DataFrame:
    from .campaign import load_strategy_frame

    return load_strategy_frame(business_date)


def _event_summary(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    """事件表统计：sent/responded 数量 + manager 渠道口径。"""
    sent = responded = 0
    manager_sent = manager_responded = 0
    sent_customers: set[str] = set()
    responded_customers: set[str] = set()
    manager_responded_customers: set[str] = set()
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT e.strategy_id, e.event_type, COUNT(*) AS count, "
                    "s.recommended_channel "
                    "FROM app_campaign_event e "
                    "LEFT JOIN ads_marketing_strategy s "
                    "ON s.strategy_date = %s "
                    "AND s.customer_id = SUBSTRING_INDEX(e.strategy_id, ':', 1) "
                    "AND s.strategy_rank = CAST(SUBSTRING_INDEX(e.strategy_id, ':', -1) "
                    "AS UNSIGNED) "
                    "WHERE e.occurred_at < %s "
                    "GROUP BY e.strategy_id, e.event_type, s.recommended_channel",
                    (business_date, business_date + timedelta(days=1)),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except Exception:
        return {
            "available": False,
            "sent": 0,
            "responded": 0,
            "manager_sent": 0,
            "manager_responded": 0,
            "sent_customers": 0,
            "responded_customers": 0,
            "manager_responded_customers": 0,
        }

    for row in rows:
        strategy_id = row["strategy_id"]
        event_type = row["event_type"]
        count = int(row["count"])
        if event_type == "sent":
            sent += count
            sent_customers.add(str(strategy_id).partition(":")[0])
            if row.get("recommended_channel") == "manager":
                manager_sent += count
        elif event_type == "responded":
            responded += count
            responded_customers.add(str(strategy_id).partition(":")[0])
            if row.get("recommended_channel") == "manager":
                manager_responded += count
                manager_responded_customers.add(str(strategy_id).partition(":")[0])
    return {
        "available": True,
        "sent": sent,
        "responded": responded,
        "manager_sent": manager_sent,
        "manager_responded": manager_responded,
        "sent_customers": len(sent_customers),
        "responded_customers": len(responded_customers),
        "manager_responded_customers": len(manager_responded_customers),
    }


def _layer_counts() -> dict:
    tables = {
        "ods": ["ods_customer", "ods_product", "ods_holding", "ods_campaign", "ods_event"],
        "dwd": ["dwd_dim_customer", "dwd_dim_product", "dwd_fact_holding", "dwd_fact_campaign", "dwd_fact_event"],
        "dws": ["dws_customer_360"],
        "ads": [
            "ads_a1_customer_product_score",
            "ads_a2_candidate_decision",
            "ads_marketing_strategy",
            "ads_portfolio_result",
            "ads_portfolio_allocation",
            "app_portfolio_scenario",
            "app_campaign_event",
        ],
    }
    counts: dict[str, int | None] = {}
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                for layer, names in tables.items():
                    total = 0
                    for name in names:
                        cursor.execute(f"SELECT COUNT(*) AS count FROM `{name}`")
                        total += int(cursor.fetchone()["count"])
                    counts[layer] = total
        finally:
            connection.close()
    except Exception:
        counts = {layer: None for layer in tables}
    return counts


def _customer_stats(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(aum),0) AS total_aum "
                "FROM dwd_dim_customer WHERE register_date <= %s",
                (business_date,),
            )
            summary = cursor.fetchone()
            cursor.execute(
                "SELECT risk_appetite AS label, COUNT(*) AS count "
                "FROM dwd_dim_customer WHERE register_date <= %s "
                "GROUP BY risk_appetite",
                (business_date,),
            )
            risk_rows = cursor.fetchall()
            cursor.execute(
                "SELECT vip_level AS label, COUNT(*) AS count "
                "FROM dwd_dim_customer WHERE register_date <= %s "
                "GROUP BY vip_level",
                (business_date,),
            )
            vip_rows = cursor.fetchall()
    finally:
        connection.close()
    return {
        "total": int(summary["total"]),
        "total_aum": round(float(summary["total_aum"]), 2),
        "risk_distribution": {row["label"]: int(row["count"]) for row in risk_rows},
        "vip_distribution": {row["label"]: int(row["count"]) for row in vip_rows},
    }


def _channel_stats(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT channel, COUNT(*) AS contacts, AVG(responded) AS response_rate "
                "FROM dwd_fact_campaign WHERE contact_date <= %s GROUP BY channel",
                (business_date,),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "SELECT COUNT(*) AS contacts, AVG(responded) AS response_rate "
                "FROM dwd_fact_campaign WHERE contact_date <= %s",
                (business_date,),
            )
            summary = cursor.fetchone()
    finally:
        connection.close()
    channels = {
        row["channel"]: {
            "contacts": int(row["contacts"]),
            "response_rate": round(float(row["response_rate"]), 4),
        }
        for row in rows
    }
    return {
        "channels": channels,
        "overall_contacts": int(summary["contacts"]),
        "overall_response_rate": round(float(summary["response_rate"] or 0), 4),
    }


def dashboard_summary(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    """Tab4 全部聚合数据，前端零计算。"""
    # ---- A1 模型指标与预测分布（dashboard_api 统一口径）----
    a1 = _a1_performance(business_date)
    probability_counts = {
        item["bucket"]: item["count"]
        for item in a1["probability_distribution"]
    }
    prediction_stats = {
        "total": int(a1.get("prediction_count") or 0),
        "mean_prob": a1.get("mean_probability"),
        "high_intent": int(probability_counts.get("高意向(≥70%)", 0)),
        "mid_intent": int(probability_counts.get("中意向(30%~70%)", 0)),
        "low_intent": int(probability_counts.get("低意向(<30%)", 0)),
    }

    # ---- 策略分布 ----
    strategies = _strategy_frame(business_date)
    a2 = _a2_performance(business_date)
    total_strategies = int(len(strategies))
    strategy_stats = {
        "status": a2["status"],
        "rows": total_strategies,
        "customers": a2["generated_customer_count"],
        "channel_distribution": {
            channel: int(count)
            for channel, count in (
                strategies["recommended_channel"].value_counts().items()
                if "recommended_channel" in strategies
                else []
            )
        },
        "time_distribution": {
            slot: int(count)
            for slot, count in (
                strategies["recommended_time"].value_counts().items()
                if "recommended_time" in strategies
                else []
            )
        },
    }

    # ---- Part B ----
    partb = _portfolio_summary(business_date)
    partb_stats = {
        "scenarios": partb["scenario_count"],
        "total_utility": partb["total_utility"],
    }

    # ---- 漏斗与 KPI ----
    events = _event_summary(business_date)
    customer_stats = _customer_stats(business_date)
    total_customers = customer_stats["total"]
    pending = max(0, total_customers - events["sent_customers"])
    funnel = {
        "stages": [
            {"stage": "全量客户", "count": total_customers},
            {"stage": "已触达客户", "count": events["sent_customers"]},
            {"stage": "已响应客户", "count": events["responded_customers"]},
        ],
        "pending": pending,
    }

    kpis = []
    for target in KPI_TARGETS:
        if target["kpi_id"] == "manager_conversion":
            actual = events["manager_responded_customers"]
        elif target["kpi_id"] == "manager_response_rate":
            actual = (
                events["manager_responded"] / events["manager_sent"]
                if events["manager_sent"]
                else 0.0
            )
        else:  # campaign_touch_progress
            actual = events["sent_customers"] / total_customers if total_customers else 0
        target_value = target["target"]
        completion = actual / target_value if target_value else 0.0
        kpis.append(
            {
                **target,
                "actual": round(actual, 6),
                "completion_rate": round(min(completion, 1.0), 4),
            }
        )

    return {
        "business_date": business_date.isoformat(),
        "model_metrics": {
            "auc": a1.get("auc"),
            "best_f1": a1.get("f1"),
            "lift_at_10_percent": a1.get("lift_at_10"),
        },
        "prediction_stats": prediction_stats,
        "strategy_stats": strategy_stats,
        "partb_stats": partb_stats,
        "customer_stats": customer_stats,
        "channel_stats": _channel_stats(business_date),
        "events": {
            "available": events["available"],
            "sent": events["sent"],
            "responded": events["responded"],
            "sent_customers": events["sent_customers"],
            "responded_customers": events["responded_customers"],
        },
        "funnel": funnel,
        "kpis": kpis,
        "data_layers": _layer_counts(),
    }
