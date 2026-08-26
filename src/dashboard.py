"""Tab4 看板聚合：KPI + 分布 + 漏斗（内存计算 + 事件表统计，零新表）。

设计（docs/demo-design.md §4）：
- KPI 目标配置在代码常量中（演示口径：固定经理 MGR001）；
- 事实来自 app_campaign_event 事件表与三份正式 CSV；
- 数据分层行数来自 MySQL 各层 COUNT（DB 不可用时返回 None）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .database import database_connection
from .partA1serving.metrics import load_validation_metrics

PROJECT_DIR = Path(__file__).resolve().parents[1]
METRICS_JSON = (
    PROJECT_DIR / "src" / "data" / "outputs" / "a1_validation_metrics.json"
)
PREDICTION_CSV = PROJECT_DIR / "partA_prediction.csv"
STRATEGY_CSV = PROJECT_DIR / "partA_strategy.csv"
PARTB_AUDIT_CSV = (
    PROJECT_DIR / "src" / "data" / "outputs" / "partB_optimality_audit.csv"
)

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


@lru_cache(maxsize=1)
def _strategy_frame() -> pd.DataFrame:
    return pd.read_csv(STRATEGY_CSV, dtype=str)


def _channel_of(strategy_id: str) -> str | None:
    customer_id, _, rank = strategy_id.partition(":")
    frame = _strategy_frame()
    rows = frame[
        (frame["customer_id"] == customer_id) & (frame["rank"] == rank)
    ]
    if not rows.empty:
        return str(rows.iloc[0]["recommended_channel"])
    try:
        from .campaign import customer_strategy_channel

        return customer_strategy_channel(customer_id, int(rank))
    except (RuntimeError, ValueError):
        return None


def _event_summary() -> dict:
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
                    "SELECT strategy_id, event_type, COUNT(*) AS count "
                    "FROM app_campaign_event GROUP BY strategy_id, event_type"
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
            if _channel_of(strategy_id) == "manager":
                manager_sent += count
        elif event_type == "responded":
            responded += count
            responded_customers.add(str(strategy_id).partition(":")[0])
            if _channel_of(strategy_id) == "manager":
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
            "ads_marketing_response_score",
            "app_marketing_strategy",
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


@lru_cache(maxsize=1)
def _customer_stats() -> dict:
    customers = pd.read_csv(
        PROJECT_DIR / "src" / "data" / "raw" / "t_customer.csv",
        dtype={"customer_id": str},
    )
    return {
        "total": int(len(customers)),
        "total_aum": round(float(customers["aum"].sum()), 2),
        "risk_distribution": {
            risk: int(count)
            for risk, count in customers["risk_appetite"].value_counts().items()
        },
        "vip_distribution": {
            vip: int(count)
            for vip, count in customers["vip_level"].value_counts().items()
        },
    }


@lru_cache(maxsize=1)
def _channel_stats() -> dict:
    campaigns = pd.read_csv(
        PROJECT_DIR / "src" / "data" / "raw" / "t_campaign.csv",
        dtype={"customer_id": str},
    )
    grouped = campaigns.groupby("channel")["responded"].agg(["count", "mean"])
    channels = {
        channel: {
            "contacts": int(row["count"]),
            "response_rate": round(float(row["mean"]), 4),
        }
        for channel, row in grouped.iterrows()
    }
    return {
        "channels": channels,
        "overall_contacts": int(len(campaigns)),
        "overall_response_rate": round(float(campaigns["responded"].mean()), 4),
    }


def dashboard_summary() -> dict:
    """Tab4 全部聚合数据，前端零计算。"""
    # ---- A1 模型指标 ----
    try:
        metrics = load_validation_metrics()
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        metrics = (
            json.loads(METRICS_JSON.read_text(encoding="utf-8"))
            if METRICS_JSON.is_file()
            else {}
        )

    # ---- 预测分布 ----
    predictions = pd.read_csv(PREDICTION_CSV)
    probabilities = pd.to_numeric(predictions["response_prob"])
    prediction_stats = {
        "total": int(len(predictions)),
        "mean_prob": round(float(probabilities.mean()), 6),
        "high_intent": int((probabilities >= 0.7).sum()),
        "mid_intent": int(((probabilities >= 0.3) & (probabilities < 0.7)).sum()),
        "low_intent": int((probabilities < 0.3).sum()),
    }

    # ---- 策略分布 ----
    strategies = _strategy_frame()
    strategy_stats = {
        "rows": int(len(strategies)),
        "customers": int(strategies["customer_id"].nunique()),
        "channel_distribution": {
            channel: int(count)
            for channel, count in strategies["recommended_channel"].value_counts().items()
        },
        "time_distribution": {
            slot: int(count)
            for slot, count in strategies["recommended_time"].value_counts().items()
        },
    }

    # ---- Part B ----
    partb_stats: dict = {}
    if PARTB_AUDIT_CSV.is_file():
        audit = pd.read_csv(PARTB_AUDIT_CSV)
        partb_stats = {
            "scenarios": int(len(audit)),
            "total_utility": round(float(audit["utility"].sum()), 12),
        }

    # ---- 漏斗与 KPI ----
    events = _event_summary()
    pending = max(0, TOTAL_CUSTOMERS - events["sent_customers"])
    funnel = {
        "stages": [
            {"stage": "全量客户", "count": TOTAL_CUSTOMERS},
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
            actual = events["sent_customers"] / TOTAL_CUSTOMERS
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
        "model_metrics": {
            "auc": metrics.get("auc"),
            "best_f1": metrics.get("best_f1"),
            "lift_at_10_percent": metrics.get("lift_at_10_percent"),
        },
        "prediction_stats": prediction_stats,
        "strategy_stats": strategy_stats,
        "partb_stats": partb_stats,
        "customer_stats": _customer_stats(),
        "channel_stats": _channel_stats(),
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
