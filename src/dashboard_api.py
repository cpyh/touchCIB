"""可视化看板 API（由 liantiao backend/app/services/dashboard_service.py 统一而来）。

契约：envelope {code, message, data}，路径 /api/v1/dashboard/overview 与 /portfolio。
数据边界：A1/A2 业务结果读取 MySQL ADS，营销漏斗读取
app_campaign_event。赛事提交 CSV 仅供离线评分，不进入营销页请求链路。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import pymysql
from flask import Blueprint, jsonify, request

from .business_date import DEFAULT_BUSINESS_DATE, parse_business_date
from .customer_api import RISK_LABELS, ServiceError, ValidationError
from .database import database_connection
from .marketing.models import CHANNELS, TIME_SLOTS
from .marketing.rules import RULES
from .partA1serving.metrics import load_validation_metrics

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


def _a1_performance(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    """A1离线评估指标 + 指定ADS批次的客户最高机会分布。"""
    try:
        metrics = load_validation_metrics()
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        metrics = {}
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total, AVG(max_prob) AS mean_prob,
                           SUM(max_prob >= 0.7) AS high_intent,
                           SUM(max_prob >= 0.3 AND max_prob < 0.7) AS mid_intent,
                           SUM(max_prob < 0.3) AS low_intent
                    FROM (
                        SELECT customer_id, MAX(response_prob) AS max_prob
                        FROM ads_a1_customer_product_score
                        WHERE strategy_date = %s
                        GROUP BY customer_id
                    ) customer_best
                    """
                , (business_date,))
                prediction = cursor.fetchone() or {}
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query A1 ADS results") from exc
    total = int(prediction["total"])
    distribution = [
        {"bucket": "高意向(≥70%)", "count": int(prediction["high_intent"] or 0)},
        {
            "bucket": "中意向(30%~70%)",
            "count": int(prediction["mid_intent"] or 0),
        },
        {"bucket": "低意向(<30%)", "count": int(prediction["low_intent"] or 0)},
    ]
    return {
        "status": "READY" if total else "NOT_READY",
        "data_source": "ADS",
        "metric_scope": "OFFLINE_VALIDATION",
        "auc": metrics.get("auc"),
        "f1": metrics.get("best_f1"),
        "lift_at_10": metrics.get("lift_at_10_percent"),
        "prediction_count": total,
        "mean_probability": (
            round(float(prediction["mean_prob"]), 6)
            if prediction["mean_prob"] is not None
            else None
        ),
        "probability_distribution": distribution,
    }


def _a2_performance(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    """A2为A1排名后的基础规则过滤；读取指定ADS日批。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM dwd_dim_customer "
                    "WHERE register_date <= %s",
                    (business_date,),
                )
                total_target = int(cursor.fetchone()["count"])
                cursor.execute(
                    "SELECT strategy_date, customer_id, strategy_rank, product_id, "
                    "recommended_channel, recommended_time, marketing_script, "
                    "rule_trace_json FROM ads_marketing_strategy "
                    "WHERE strategy_date=%s",
                    (business_date,),
                )
                strategies = list(cursor.fetchall())
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query A2 ADS results") from exc

    grouped: dict[str, list[dict]] = {}
    for row in strategies:
        grouped.setdefault(str(row["customer_id"]), []).append(row)
    valid_customers = sum(
        len(rows) == 3
        and {int(row["strategy_rank"]) for row in rows} == {1, 2, 3}
        and len({row["product_id"] for row in rows}) == 3
        for rows in grouped.values()
    )
    generated = int(valid_customers)
    channel_counts: dict[str, int] = {}
    time_counts: dict[str, int] = {}
    traces_valid = True
    for row in strategies:
        channel_counts[row["recommended_channel"]] = channel_counts.get(row["recommended_channel"], 0) + 1
        time_counts[row["recommended_time"]] = time_counts.get(row["recommended_time"], 0) + 1
        try:
            trace = json.loads(row["rule_trace_json"]) if isinstance(row["rule_trace_json"], str) else row["rule_trace_json"]
            traces_valid = traces_valid and isinstance(trace, list) and all(item.get("passed") for item in trace)
        except (json.JSONDecodeError, TypeError, AttributeError):
            traces_valid = False
    channel_distribution = [
        {"channel": channel, "count": int(channel_counts.get(channel, 0))}
        for channel in CHANNELS
    ]
    time_distribution = [
        {"time_slot": time_slot, "count": int(time_counts.get(time_slot, 0))}
        for time_slot in TIME_SLOTS
    ]
    validation = {
        "customer_coverage_passed": generated == total_target,
        "top3_complete_passed": generated == len(grouped),
        "product_unique_passed": all(len({row["product_id"] for row in rows}) == 3 for rows in grouped.values()),
        "channel_enum_passed": {row["recommended_channel"] for row in strategies}.issubset(CHANNELS),
        "time_enum_passed": {row["recommended_time"] for row in strategies}.issubset(TIME_SLOTS),
        "script_length_passed": all(10 <= len(str(row["marketing_script"])) <= 300 for row in strategies),
        "rule_trace_passed": traces_valid,
    }
    status = (
        "READY"
        if total_target and generated == total_target and all(validation.values())
        else "INVALID"
        if strategies
        else "NOT_READY"
    )
    return {
        "status": status,
        "data_source": "ADS",
        "result_row_count": len(strategies),
        "target_customer_count": total_target,
        "generated_customer_count": generated,
        "coverage_rate": round(generated / total_target, 4) if total_target else None,
        "hit_rate_at_3": None,
        "rule_count": len(RULES),
        "channel_distribution": channel_distribution,
        "time_distribution": time_distribution,
        "validation": validation,
    }


def _portfolio_summary(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    """汇总指定ADS组合优化批次。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS scenario_count, "
                    "COALESCE(SUM(constraints_satisfied),0) AS passed_count, "
                    "SUM(utility) AS total_utility, MAX(optimality_gap) AS max_gap "
                    "FROM ads_portfolio_result WHERE calculation_date=%s",
                    (business_date,),
                )
                summary = cursor.fetchone() or {}
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM ads_portfolio_allocation "
                    "WHERE calculation_date=%s",
                    (business_date,),
                )
                allocation_count = int(cursor.fetchone()["count"])
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query Part B ADS summary") from exc
    scenario_count = int(summary.get("scenario_count") or 0)
    passed_count = int(summary.get("passed_count") or 0)
    return {
        "status": (
            "NOT_READY"
            if not scenario_count
            else "READY"
            if passed_count == scenario_count
            else "INVALID"
        ),
        "scenario_count": scenario_count,
        "constraints_passed_count": passed_count,
        "allocation_row_count": allocation_count,
        "total_utility": round(float(summary["total_utility"]), 12) if scenario_count else None,
        "max_optimality_gap": float(summary["max_gap"]) if summary.get("max_gap") is not None else None,
    }


def _portfolio_performance(
    scenario_id: str | None,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    """Part B只读取场景配置和指定ADS批处理结果。"""
    if scenario_id is None:
        return {
            "status": "NOT_READY",
            "data_source": "ADS",
            "scenario_id": None,
            "total_amount": None,
            "expected_return": None,
            "volatility": None,
            "utility": None,
            "cash_weight": None,
            "constraints_satisfied": None,
            "allocation_by_product_type": [],
            "allocation_items": [],
        }
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM app_portfolio_scenario WHERE scenario_id=%s",
                    (scenario_id,),
                )
                scenario = cursor.fetchone()
                cursor.execute(
                    "SELECT * FROM ads_portfolio_result WHERE scenario_id=%s "
                    "AND calculation_date=%s LIMIT 1",
                    (scenario_id, business_date),
                )
                result = cursor.fetchone()
                allocation_rows: list[dict] = []
                if result is not None:
                    cursor.execute(
                        "SELECT a.product_id, p.product_name, p.product_type, "
                        "p.risk_level, a.weight, a.allocation_amount "
                        "FROM ads_portfolio_allocation a "
                        "JOIN dwd_dim_product p ON p.product_id=a.product_id "
                        "WHERE a.calculation_date=%s AND a.scenario_id=%s "
                        "ORDER BY a.weight DESC, a.product_id",
                        (result["calculation_date"], scenario_id),
                    )
                    allocation_rows = list(cursor.fetchall())
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query Part B ADS results") from exc
    if scenario is None:
        raise ValidationError("scenario not found")
    if result is None:
        return {
            "status": "NOT_READY",
            "data_source": "ADS",
            "scenario_id": scenario_id,
            "total_amount": float(scenario["total_amount"]),
            "expected_return": None,
            "volatility": None,
            "utility": None,
            "cash_weight": None,
            "constraints_satisfied": None,
            "allocation_by_product_type": [],
            "allocation_items": [],
        }

    type_amounts: dict[str, float] = {}
    for row in allocation_rows:
        product_type = str(row["product_type"])
        type_amounts[product_type] = type_amounts.get(product_type, 0.0) + float(row["weight"])
    allocation_by_type = [
        {"product_type": product_type, "weight": round(weight, 6)}
        for product_type, weight in sorted(type_amounts.items())
    ]
    allocation_items = [
        {
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "product_type": row["product_type"],
            "risk_level": row["risk_level"],
            "weight": round(float(row["weight"]), 12),
            "allocation_amount": float(row["allocation_amount"]),
        }
        for row in allocation_rows
    ]
    return {
        "status": "READY",
        "data_source": "ADS",
        "scenario_id": scenario_id,
        "total_amount": float(scenario["total_amount"]),
        "expected_return": round(float(result["expected_return"]), 12),
        "volatility": round(float(result["portfolio_volatility"]), 12),
        "utility": round(float(result["utility"]), 12),
        "cash_weight": round(float(result["cash_weight"]), 12),
        "constraints_satisfied": bool(result["constraints_satisfied"]),
        "optimality_gap": float(result["optimality_gap"]) if result["optimality_gap"] is not None else None,
        "allocation_by_product_type": allocation_by_type,
        "allocation_items": allocation_items,
    }


def _marketing_funnel(
    business_date: date = DEFAULT_BUSINESS_DATE,
    *,
    a2_performance: dict | None = None,
    total_customers: int | None = None,
) -> dict:
    """营销闭环同时返回客户口径与 strategy_id 事件口径。"""
    event_counts = {
        "sent": {"strategies": 0, "customers": 0},
        "responded": {"strategies": 0, "customers": 0},
    }
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT event_type, COUNT(DISTINCT strategy_id) AS strategies, "
                    "COUNT(DISTINCT SUBSTRING_INDEX(strategy_id, ':', 1)) AS customers "
                    "FROM app_campaign_event WHERE event_type IN ('sent', 'responded') "
                    "AND occurred_at < %s GROUP BY event_type",
                    (business_date + timedelta(days=1),),
                )
                for row in cursor.fetchall():
                    event_counts[str(row["event_type"])] = row
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        pass
    sent = event_counts["sent"]
    responded = event_counts["responded"]
    sent_strategy_count = int(sent["strategies"] or 0)
    responded_strategy_count = int(responded["strategies"] or 0)
    a2 = a2_performance if a2_performance is not None else _a2_performance(business_date)
    if total_customers is None:
        try:
            connection = database_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM ods_customer "
                        "WHERE register_date <= %s",
                        (business_date,),
                    )
                    total_customers = int(cursor.fetchone()["count"])
            finally:
                connection.close()
        except (pymysql.MySQLError, OSError, ValueError):
            total_customers = 0
    return {
        "status": "READY" if sent_strategy_count or responded_strategy_count else "NOT_STARTED",
        "target_customer_count": total_customers,
        "generated_customer_count": a2["generated_customer_count"],
        "contacted_customer_count": int(sent["customers"] or 0) if sent else 0,
        "responded_customer_count": int(responded["customers"] or 0) if responded else 0,
        "generated_strategy_count": a2.get("result_row_count", 0),
        "sent_strategy_count": sent_strategy_count,
        "responded_strategy_count": responded_strategy_count,
    }


def _action_items(
    business_date: date = DEFAULT_BUSINESS_DATE,
    *,
    high_intent_untouched: int | None = None,
    total_customer_count: int | None = None,
) -> dict:
    """运营行动指令：目标-实际-缺口，供看板"今日行动"指挥工作台执行。"""
    sent_strategies = 0
    manager_sent = 0
    manager_responded = 0
    sent_customer_count = 0
    strategy_ready_customers = 0
    total_strategies = 0
    resolved_high_intent = int(high_intent_untouched or 0)
    resolved_total_customers = int(total_customer_count or 0)
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total_strategies, "
                    "COUNT(DISTINCT customer_id) AS strategy_ready_customers "
                    "FROM ads_marketing_strategy WHERE strategy_date=%s",
                    (business_date,),
                )
                strategy_stats = cursor.fetchone() or {}
                total_strategies = int(strategy_stats.get("total_strategies") or 0)
                strategy_ready_customers = int(
                    strategy_stats.get("strategy_ready_customers") or 0
                )
                cursor.execute(
                    "SELECT "
                    "COALESCE(SUM(e.event_type='sent'), 0) AS sent_strategies, "
                    "COUNT(DISTINCT CASE WHEN e.event_type='sent' THEN "
                    "SUBSTRING_INDEX(e.strategy_id, ':', 1) END) AS sent_customers, "
                    "COALESCE(SUM(e.event_type='sent' AND "
                    "s.recommended_channel='manager'), 0) AS manager_sent, "
                    "COALESCE(SUM(e.event_type='responded' AND "
                    "s.recommended_channel='manager'), 0) AS manager_responded "
                    "FROM app_campaign_event e "
                    "LEFT JOIN ads_marketing_strategy s "
                    "ON s.strategy_date=%s "
                    "AND s.customer_id=SUBSTRING_INDEX(e.strategy_id, ':', 1) "
                    "AND s.strategy_rank=CAST(SUBSTRING_INDEX(e.strategy_id, ':', -1) "
                    "AS UNSIGNED) "
                    "WHERE e.occurred_at < %s",
                    (business_date, business_date + timedelta(days=1)),
                )
                event_stats = cursor.fetchone() or {}
                sent_strategies = int(event_stats.get("sent_strategies") or 0)
                sent_customer_count = int(event_stats.get("sent_customers") or 0)
                manager_sent = int(event_stats.get("manager_sent") or 0)
                manager_responded = int(event_stats.get("manager_responded") or 0)
                if high_intent_untouched is None:
                    cursor.execute(
                        "WITH sent AS ("
                        "SELECT DISTINCT SUBSTRING_INDEX(strategy_id, ':', 1) "
                        "AS customer_id FROM app_campaign_event "
                        "WHERE event_type='sent' AND occurred_at < %s) "
                        "SELECT COUNT(*) AS count "
                        "FROM ads_a1_customer_product_score a "
                        "LEFT JOIN sent e ON e.customer_id=a.customer_id "
                        "WHERE a.strategy_date=%s AND a.a1_rank=1 "
                        "AND a.response_prob >= 0.7 AND e.customer_id IS NULL",
                        (business_date + timedelta(days=1), business_date),
                    )
                    resolved_high_intent = int(cursor.fetchone()["count"])
                if total_customer_count is None:
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM dwd_dim_customer "
                        "WHERE register_date <= %s",
                        (business_date,),
                    )
                    resolved_total_customers = int(cursor.fetchone()["count"])
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        pass

    conversion_target = 30
    return {
        "conversion": {
            "actual": manager_responded,
            "target": conversion_target,
            "gap": max(0, conversion_target - manager_responded),
            "label": f"经理 MGR001 {business_date.month}月转化",
        },
        "touch": {
            "total_customers": resolved_total_customers,
            "sent_customers": sent_customer_count,
            "strategy_ready_customers": strategy_ready_customers,
            "sent_strategies": sent_strategies,
            "total_strategies": total_strategies,
            "high_intent_untouched": resolved_high_intent,
        },
        "channel": {
            "manager_sent": manager_sent,
            "manager_responded": manager_responded,
            "manager_response_rate": (
                round(manager_responded / manager_sent, 4)
                if manager_sent
                else None
            ),
            "manager_target": 0.25,
        },
    }


def _expiry_warning(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    """到期预警：未来 30 天固定期限持仓到期（再配置/挽留机会）。

    口径：maturity = buy_date + duration_days，窗口 = 策略日次日至 +30 天。
    """
    as_of = business_date
    window_end = as_of + timedelta(days=30)
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT h.customer_id, h.product_id, p.product_name,
                           h.amount,
                           DATE_ADD(h.buy_date, INTERVAL p.duration_days DAY)
                               AS maturity_date
                    FROM ods_holding h
                    JOIN ods_product p ON p.product_id = h.product_id
                    WHERE p.duration_days > 0
                      AND DATE_ADD(h.buy_date, INTERVAL p.duration_days DAY) > %s
                      AND DATE_ADD(h.buy_date, INTERVAL p.duration_days DAY) <= %s
                    ORDER BY maturity_date, h.amount DESC
                    """,
                    (as_of, window_end),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError, TypeError):
        return {
            "available": False,
            "as_of": as_of.isoformat(),
            "window_days": 30,
            "holding_count": 0,
            "customer_count": 0,
            "amount": 0,
            "items": [],
        }

    customers = {row["customer_id"] for row in rows}
    total_amount = sum(float(row["amount"]) for row in rows)
    return {
        "available": True,
        "as_of": as_of.isoformat(),
        "window_days": 30,
        "holding_count": len(rows),
        "customer_count": len(customers),
        "amount": round(total_amount, 2),
        "items": [
            {
                "customer_id": row["customer_id"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "maturity_date": row["maturity_date"].isoformat(),
                "amount": float(row["amount"]),
            }
            for row in rows[:5]
        ],
    }


def _opportunity(
    business_date: date = DEFAULT_BUSINESS_DATE,
    *,
    expiry_warning: dict | None = None,
) -> dict:
    """转化机会挖掘：从最新A1 ADS批次与事件中聚合。

    - golden：高意向（≥70%）未触达客户 + 期望响应数（Σ 客户最高概率）
    - products：产品机会榜（高意向未触达触达记录按产品聚合 Top3）
    - expiry：到期承接窗口（来自 _expiry_warning）
    """
    product_rows: list[dict] = []
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH sent AS (
                        SELECT DISTINCT SUBSTRING_INDEX(strategy_id, ':', 1)
                            AS customer_id
                        FROM app_campaign_event WHERE event_type='sent'
                          AND occurred_at < %s
                    )
                    SELECT a.product_id,
                           COUNT(*) AS customer_count,
                           SUM(a.response_prob) AS expected_responses
                    FROM ads_a1_customer_product_score a
                    LEFT JOIN sent e ON e.customer_id=a.customer_id
                    WHERE a.strategy_date=%s AND a.a1_rank=1
                      AND a.response_prob >= 0.7 AND e.customer_id IS NULL
                    GROUP BY a.product_id
                    """
                , (business_date + timedelta(days=1), business_date))
                product_rows = list(cursor.fetchall())
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        product_rows = []

    golden = {
        "count": sum(int(row["customer_count"] or 0) for row in product_rows),
        "expected_responses": int(
            round(sum(float(row["expected_responses"] or 0) for row in product_rows))
        ),
    }
    product_opportunity = [
        {"product_id": str(row["product_id"]), "count": int(row["customer_count"])}
        for row in sorted(
            product_rows,
            key=lambda item: (-int(item["customer_count"]), str(item["product_id"])),
        )[:3]
    ]

    return {
        "golden": golden,
        "products": product_opportunity,
        "expiry": (
            expiry_warning
            if expiry_warning is not None
            else _expiry_warning(business_date)
        ),
    }


def get_dashboard_overview(
    *,
    scenario_id: str | None = None,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM ods_customer
                         WHERE register_date <= %s) AS customer_count,
                        (SELECT COALESCE(SUM(aum), 0) FROM ods_customer
                         WHERE register_date <= %s) AS total_aum,
                        (SELECT COUNT(*) FROM ods_product) AS product_count,
                        (SELECT COALESCE(SUM(h.amount), 0) FROM ods_holding h
                         JOIN ods_customer c ON c.customer_id=h.customer_id
                         WHERE h.buy_date <= %s AND c.register_date <= %s)
                            AS total_holding_amount,
                        (SELECT COUNT(*) FROM ods_campaign
                         WHERE contact_date <= %s)
                            AS historical_contact_count,
                        (SELECT COALESCE(AVG(responded), 0) FROM ods_campaign
                         WHERE contact_date <= %s)
                            AS historical_response_rate
                    """,
                    (
                        business_date,
                        business_date,
                        business_date,
                        business_date,
                        business_date,
                        business_date,
                    ),
                )
                metrics = cursor.fetchone()
                cursor.execute(
                    "SELECT risk_appetite, COUNT(*) AS customer_count "
                    "FROM ods_customer WHERE register_date <= %s "
                    "GROUP BY risk_appetite",
                    (business_date,),
                )
                risk_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT p.product_type, COALESCE(SUM(h.amount), 0) AS holding_amount
                    FROM ods_holding h
                    JOIN ods_product p ON p.product_id = h.product_id
                    JOIN ods_customer c ON c.customer_id = h.customer_id
                    WHERE h.buy_date <= %s AND c.register_date <= %s
                    GROUP BY p.product_type
                    """,
                    (business_date, business_date),
                )
                holding_rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError, TypeError) as exc:
        raise ServiceError("unable to query dashboard overview") from exc

    total_aum = _decimal(metrics["total_aum"])
    total_holding_amount = _decimal(metrics["total_holding_amount"])
    a1_performance = _a1_performance(business_date)
    a2_performance = _a2_performance(business_date)
    portfolio_summary = _portfolio_summary(business_date)
    expiry_warning = _expiry_warning(business_date)
    opportunity = _opportunity(
        business_date,
        expiry_warning=expiry_warning,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "business_date": business_date.isoformat(),
        "business_metrics": {
            "customer_count": int(metrics["customer_count"]),
            "total_aum": float(total_aum),
            "product_count": int(metrics["product_count"]),
            "total_holding_amount": float(total_holding_amount),
            "currency": "CNY",
            "historical_contact_count": int(metrics["historical_contact_count"]),
            "historical_response_rate": round(float(metrics["historical_response_rate"]), 4),
            "marketing_status": a2_performance["status"],
        },
        "risk_distribution": build_risk_distribution(risk_rows),
        "holding_distribution": build_holding_distribution(
            holding_rows, total_holding_amount
        ),
        "a1_performance": a1_performance,
        "a2_performance": a2_performance,
        "portfolio_summary": portfolio_summary,
        "portfolio": _portfolio_performance(scenario_id, business_date),
        "marketing_funnel": _marketing_funnel(
            business_date,
            a2_performance=a2_performance,
            total_customers=int(metrics["customer_count"]),
        ),
        "action_items": _action_items(
            business_date,
            high_intent_untouched=opportunity["golden"]["count"],
            total_customer_count=int(metrics["customer_count"]),
        ),
        "expiry_warning": expiry_warning,
        "opportunity": opportunity,
    }


def get_home_overview(
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    """首页轻量聚合：只返回页面实际使用的经营动作与到期预警。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS customer_count, "
                    "COALESCE(SUM(aum), 0) AS total_aum "
                    "FROM ods_customer WHERE register_date <= %s",
                    (business_date,),
                )
                metrics = cursor.fetchone() or {}
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError, TypeError) as exc:
        raise ServiceError("unable to query home overview") from exc

    customer_count = int(metrics.get("customer_count") or 0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "business_date": business_date.isoformat(),
        "business_metrics": {
            "customer_count": customer_count,
            "total_aum": float(_decimal(metrics.get("total_aum"))),
            "currency": "CNY",
        },
        "action_items": _action_items(
            business_date,
            total_customer_count=customer_count,
        ),
        "expiry_warning": _expiry_warning(business_date),
    }


def get_dashboard_portfolio(
    scenario_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    return _portfolio_performance(scenario_id, business_date)


# ----------------------------------------------------------------
# 路由
# ----------------------------------------------------------------

dashboard_bp = Blueprint(
    "dashboard_v1", __name__, url_prefix="/api/v1/dashboard"
)


def success(data, status: int = 200):
    return jsonify({"code": 0, "message": "success", "data": data}), status


def _optional_scenario_id() -> str | None:
    value = request.args.get("scenario_id")
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > 64:
        raise ValidationError("invalid scenario_id")
    return value


def _request_business_date() -> date:
    try:
        return parse_business_date(request.args.get("business_date"))
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@dashboard_bp.get("/overview")
def dashboard_overview():
    business_date = _request_business_date()
    return success(
        get_dashboard_overview(
            scenario_id=_optional_scenario_id(),
            business_date=business_date,
        )
    )


@dashboard_bp.get("/home")
def dashboard_home():
    return success(get_home_overview(_request_business_date()))


@dashboard_bp.get("/portfolio")
def dashboard_portfolio():
    scenario_id = _optional_scenario_id()
    if scenario_id is None:
        raise ValidationError("scenario_id is required")
    business_date = _request_business_date()
    return success(get_dashboard_portfolio(scenario_id, business_date))


@dashboard_bp.errorhandler(ValidationError)
def handle_validation_error(exc):
    return jsonify({"code": 400, "message": str(exc), "data": None}), 400


@dashboard_bp.errorhandler(ServiceError)
def handle_service_error(exc):
    return jsonify({"code": 503, "message": str(exc), "data": None}), 503
