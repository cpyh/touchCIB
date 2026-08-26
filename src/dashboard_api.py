"""可视化看板 API（由 liantiao backend/app/services/dashboard_service.py 统一而来）。

契约：envelope {code, message, data}，路径 /api/v1/dashboard/overview 与 /portfolio。
数据边界：A1 预测读取 MySQL，A2 读取正式策略 CSV，Part B 读取正式配置 CSV
及其审计文件，营销漏斗读取 app_campaign_event。看板请求本身不运行算法。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pymysql
from flask import Blueprint, jsonify, request

from .customer_api import RISK_LABELS, ServiceError, ValidationError
from .database import database_connection
from .marketing.models import CHANNELS, TIME_SLOTS
from .marketing.rules import RULES
from .partA1serving.metrics import load_validation_metrics

PROJECT_DIR = Path(__file__).resolve().parents[1]
METRICS_JSON = (
    PROJECT_DIR / "src" / "data" / "outputs" / "a1_validation_metrics.json"
)
PREDICTION_CSV = PROJECT_DIR / "partA_prediction.csv"
STRATEGY_CSV = PROJECT_DIR / "partA_strategy.csv"
STRATEGY_TARGET_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_strategy_customers.csv"
)
TEST_CONTACTS_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_test_contacts.csv"
)
ALLOCATION_CSV = PROJECT_DIR / "partB_allocation.csv"
PARTB_AUDIT_CSV = (
    PROJECT_DIR / "src" / "data" / "outputs" / "partB_optimality_audit.csv"
)
PRODUCT_CSV = PROJECT_DIR / "src" / "data" / "raw" / "t_product.csv"
SCENARIO_CSV = PROJECT_DIR / "src" / "data" / "raw" / "partB_scenarios.csv"

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


def _a1_performance() -> dict:
    """A1 指标取 partA1serving 验证口径，预测分布读正式提交 CSV。"""
    import pandas as pd

    try:
        metrics = load_validation_metrics()
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        if not METRICS_JSON.is_file():
            return {
                "status": "NOT_READY",
                "data_source": "CSV",
                "auc": None,
                "f1": None,
                "lift_at_10": None,
                "prediction_count": 0,
                "mean_probability": None,
                "probability_distribution": [],
            }
        metrics = json.loads(METRICS_JSON.read_text(encoding="utf-8"))
    try:
        probabilities = pd.to_numeric(
            pd.read_csv(PREDICTION_CSV)["response_prob"]
        )
    except (OSError, ValueError) as exc:
        raise ServiceError("unable to read A1 prediction results") from exc
    prediction = {
        "total": int(len(probabilities)),
        "mean_prob": float(probabilities.mean()),
        "high_intent": int((probabilities >= 0.7).sum()),
        "mid_intent": int(
            ((probabilities >= 0.3) & (probabilities < 0.7)).sum()
        ),
        "low_intent": int((probabilities < 0.3).sum()),
    }
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
        "data_source": "CSV",
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


def _a2_performance() -> dict:
    """A2 使用正式提交 CSV；隐藏标签不可用，因此 HitRate 保持为空。"""
    import pandas as pd

    if not STRATEGY_CSV.is_file() or not STRATEGY_TARGET_CSV.is_file():
        return {
            "status": "NOT_READY",
            "data_source": "CSV",
            "result_row_count": 0,
            "target_customer_count": 0,
            "generated_customer_count": 0,
            "coverage_rate": None,
            "hit_rate_at_3": None,
            "rule_count": len(RULES),
            "channel_distribution": [],
            "time_distribution": [],
            "validation": {},
        }
    try:
        strategies = pd.read_csv(STRATEGY_CSV, dtype=str)
        targets = pd.read_csv(STRATEGY_TARGET_CSV, dtype=str)
    except (OSError, ValueError) as exc:
        raise ServiceError("unable to read A2 strategy results") from exc

    required = {
        "customer_id",
        "rank",
        "product_id",
        "recommended_channel",
        "recommended_time",
        "marketing_script",
    }
    if not required.issubset(strategies.columns) or "customer_id" not in targets:
        raise ServiceError("invalid A2 strategy file columns")

    target_ids = set(targets["customer_id"].dropna())
    strategy_ids = set(strategies["customer_id"].dropna())
    valid_customers = 0
    for customer_id, rows in strategies.groupby("customer_id"):
        ranks = set(rows["rank"])
        products = set(rows["product_id"])
        if len(rows) == 3 and ranks == {"1", "2", "3"} and len(products) == 3:
            valid_customers += 1
    total_target = len(target_ids)
    generated = valid_customers
    channel_counts = strategies["recommended_channel"].value_counts().to_dict()
    channel_distribution = [
        {"channel": channel, "count": int(channel_counts.get(channel, 0))}
        for channel in CHANNELS
    ]
    time_counts = strategies["recommended_time"].value_counts().to_dict()
    time_distribution = [
        {"time_slot": time_slot, "count": int(time_counts.get(time_slot, 0))}
        for time_slot in TIME_SLOTS
    ]
    grouped = strategies.groupby("customer_id")
    validation = {
        "customer_coverage_passed": strategy_ids == target_ids,
        "top3_complete_passed": bool(
            len(grouped) == total_target
            and all(len(rows) == 3 and set(rows["rank"]) == {"1", "2", "3"}
                    for _, rows in grouped)
        ),
        "product_unique_passed": bool(
            len(grouped) == total_target
            and all(rows["product_id"].nunique() == 3 for _, rows in grouped)
        ),
        "channel_enum_passed": set(strategies["recommended_channel"].dropna()).issubset(CHANNELS),
        "time_enum_passed": set(strategies["recommended_time"].dropna()).issubset(TIME_SLOTS),
        "script_length_passed": bool(
            strategies["marketing_script"].notna().all()
            and strategies["marketing_script"].str.len().between(10, 300).all()
        ),
    }
    unknown_customers = strategy_ids - target_ids
    status = (
        "READY"
        if generated == total_target and not unknown_customers and all(validation.values())
        else "INVALID"
    )
    return {
        "status": status,
        "data_source": "CSV",
        "result_row_count": int(len(strategies)),
        "target_customer_count": total_target,
        "generated_customer_count": generated,
        "coverage_rate": round(generated / total_target, 4) if total_target else None,
        "hit_rate_at_3": None,
        "rule_count": len(RULES),
        "channel_distribution": channel_distribution,
        "time_distribution": time_distribution,
        "validation": validation,
    }


def _portfolio_summary() -> dict:
    """汇总正式 Part B 结果，供看板展示 20 个场景的整体质量。"""
    import pandas as pd

    if not ALLOCATION_CSV.is_file() or not PARTB_AUDIT_CSV.is_file():
        return {
            "status": "NOT_READY",
            "scenario_count": 0,
            "constraints_passed_count": 0,
            "allocation_row_count": 0,
            "total_utility": None,
            "max_optimality_gap": None,
        }
    try:
        allocations = pd.read_csv(ALLOCATION_CSV, dtype={"scenario_id": str})
        audit = pd.read_csv(PARTB_AUDIT_CSV, dtype={"scenario_id": str})
    except (OSError, ValueError) as exc:
        raise ServiceError("unable to read Part B summary") from exc

    passed = (
        (audit["product_weight_sum"] <= 1 + 1e-6)
        & (audit["high_risk_weight"] <= audit["high_risk_cap"] + 1e-6)
        & (audit["liquid_plus_cash"] + 1e-6 >= audit["liquid_floor"])
        & (audit["holdings_count"] >= audit["required_min_holdings"])
        & (audit["max_product_weight"] <= audit["single_product_cap"] + 1e-6)
    )
    scenario_count = int(audit["scenario_id"].nunique())
    passed_count = int(passed.sum())
    return {
        "status": "READY" if scenario_count and passed_count == scenario_count else "INVALID",
        "scenario_count": scenario_count,
        "constraints_passed_count": passed_count,
        "allocation_row_count": int(len(allocations)),
        "total_utility": round(float(audit["utility"].sum()), 12) if scenario_count else None,
        "max_optimality_gap": float(audit["absolute_gap_bound"].max()) if scenario_count else None,
    }


def _portfolio_performance(scenario_id: str | None) -> dict:
    """Part B 使用正式配置 CSV 和审计文件，不在看板请求中重新求解。"""
    if scenario_id is None:
        return {
            "status": "NOT_READY",
            "data_source": "CSV",
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
    import pandas as pd

    required_files = (ALLOCATION_CSV, PARTB_AUDIT_CSV, PRODUCT_CSV, SCENARIO_CSV)
    if not all(path.is_file() for path in required_files):
        return {
            "status": "NOT_READY",
            "data_source": "CSV",
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
    try:
        allocations = pd.read_csv(
            ALLOCATION_CSV, dtype={"scenario_id": str, "product_id": str}
        )
        audit = pd.read_csv(PARTB_AUDIT_CSV, dtype={"scenario_id": str})
        products = pd.read_csv(PRODUCT_CSV, dtype={"product_id": str})
        scenarios = pd.read_csv(SCENARIO_CSV, dtype={"scenario_id": str})
    except (OSError, ValueError) as exc:
        raise ServiceError("unable to read Part B results") from exc

    scenario_rows = scenarios[scenarios["scenario_id"] == scenario_id]
    result_rows = allocations[allocations["scenario_id"] == scenario_id].copy()
    audit_rows = audit[audit["scenario_id"] == scenario_id]
    if scenario_rows.empty:
        raise ValidationError("scenario not found")
    if result_rows.empty or audit_rows.empty:
        return {
            "status": "NOT_READY",
            "data_source": "CSV",
            "scenario_id": scenario_id,
            "total_amount": float(scenario_rows.iloc[0]["total_amount"]),
            "expected_return": None,
            "volatility": None,
            "utility": None,
            "cash_weight": None,
            "constraints_satisfied": None,
            "allocation_by_product_type": [],
            "allocation_items": [],
        }

    result_rows["weight"] = pd.to_numeric(result_rows["weight"], errors="raise")
    result_rows = result_rows.merge(
        products[
            ["product_id", "product_name", "product_type", "risk_level"]
        ],
        on="product_id",
        how="left",
        validate="many_to_one",
    )
    if result_rows["product_name"].isna().any():
        raise ServiceError("Part B result contains unknown product")
    scenario = scenario_rows.iloc[0]
    audit_row = audit_rows.iloc[0]
    weight_sum = float(result_rows["weight"].sum())
    type_amounts = result_rows.groupby("product_type")["weight"].sum()
    allocation_by_type = [
        {"product_type": product_type, "weight": round(weight, 6)}
        for product_type, weight in sorted(type_amounts.to_dict().items())
    ]
    allocation_items = [
        {
            "product_id": row.product_id,
            "product_name": row.product_name,
            "product_type": row.product_type,
            "risk_level": row.risk_level,
            "weight": round(float(row.weight), 12),
            "allocation_amount": round(
                float(row.weight) * float(scenario["total_amount"]), 2
            ),
        }
        for row in result_rows.itertuples()
    ]
    constraints_satisfied = bool(
        float(audit_row["product_weight_sum"]) <= 1 + 1e-6
        and float(audit_row["high_risk_weight"])
        <= float(audit_row["high_risk_cap"]) + 1e-6
        and float(audit_row["liquid_plus_cash"]) + 1e-6
        >= float(audit_row["liquid_floor"])
        and int(audit_row["holdings_count"])
        >= int(audit_row["required_min_holdings"])
        and float(audit_row["max_product_weight"])
        <= float(audit_row["single_product_cap"]) + 1e-6
    )
    return {
        "status": "READY",
        "data_source": "CSV",
        "scenario_id": scenario_id,
        "total_amount": float(scenario["total_amount"]),
        "expected_return": round(float(audit_row["expected_return"]), 12),
        "volatility": round(float(audit_row["portfolio_volatility"]), 12),
        "utility": round(float(audit_row["utility"]), 12),
        "cash_weight": round(max(0.0, 1.0 - weight_sum), 12),
        "constraints_satisfied": constraints_satisfied,
        "optimality_gap": float(audit_row["absolute_gap_bound"]),
        "allocation_by_product_type": allocation_by_type,
        "allocation_items": allocation_items,
    }


def _marketing_funnel() -> dict:
    """营销闭环同时返回客户口径与 strategy_id 事件口径。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(DISTINCT strategy_id) AS strategies, "
                    "COUNT(DISTINCT SUBSTRING_INDEX(strategy_id, ':', 1)) AS customers "
                    "FROM app_campaign_event WHERE event_type = 'sent'"
                )
                sent = cursor.fetchone() or {}
                cursor.execute(
                    "SELECT COUNT(DISTINCT strategy_id) AS strategies, "
                    "COUNT(DISTINCT SUBSTRING_INDEX(strategy_id, ':', 1)) AS customers "
                    "FROM app_campaign_event WHERE event_type = 'responded'"
                )
                responded = cursor.fetchone() or {}
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        sent = {"strategies": 0, "customers": 0}
        responded = {"strategies": 0, "customers": 0}
    sent_strategy_count = int(sent["strategies"] or 0) if sent else 0
    responded_strategy_count = int(responded["strategies"] or 0) if responded else 0
    a2 = _a2_performance()
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM ods_customer")
                total_customers = int(cursor.fetchone()["count"])
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        total_customers = 0
    return {
        "status": "READY" if sent_strategy_count or responded_strategy_count else "NOT_STARTED",
        # 平台运营口径：全量客户为目标；官方 A2 判分集合另列
        "target_customer_count": total_customers,
        "official_target_customer_count": a2["target_customer_count"],
        "generated_customer_count": a2["generated_customer_count"],
        "contacted_customer_count": int(sent["customers"] or 0) if sent else 0,
        "responded_customer_count": int(responded["customers"] or 0) if responded else 0,
        "generated_strategy_count": a2.get("result_row_count", 0),
        "sent_strategy_count": sent_strategy_count,
        "responded_strategy_count": responded_strategy_count,
    }


def _action_items() -> dict:
    """运营行动指令：目标-实际-缺口，供看板"今日行动"指挥工作台执行。"""
    import pandas as pd

    strategy_channels: dict[tuple[str, str], str] = {}
    if STRATEGY_CSV.is_file():
        try:
            strategies = pd.read_csv(STRATEGY_CSV, dtype=str)
            strategy_channels = {
                (row.customer_id, row.rank): row.recommended_channel
                for row in strategies.itertuples()
            }
        except (OSError, ValueError):
            pass

    sent_strategies = 0
    manager_sent = 0
    manager_responded = 0
    sent_customers: set[str] = set()
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
        for row in rows:
            strategy_id = str(row["strategy_id"])
            customer_id, _, rank = strategy_id.partition(":")
            channel = strategy_channels.get((customer_id, rank))
            count = int(row["count"])
            if row["event_type"] == "sent":
                sent_strategies += count
                sent_customers.add(customer_id)
                if channel == "manager":
                    manager_sent += count
            elif row["event_type"] == "responded" and channel == "manager":
                manager_responded += count
    except (pymysql.MySQLError, OSError, ValueError):
        pass

    high_intent_customers: set[str] = set()
    try:
        contacts = pd.read_csv(TEST_CONTACTS_CSV, dtype={"customer_id": str})
        predictions = pd.read_csv(PREDICTION_CSV, dtype={"contact_id": str})
        merged = contacts.merge(predictions, on="contact_id", how="left")
        merged["response_prob"] = pd.to_numeric(
            merged["response_prob"], errors="coerce"
        )
        high_intent_customers = set(
            merged.loc[merged["response_prob"] >= 0.7, "customer_id"].dropna()
        )
    except (OSError, ValueError, KeyError):
        high_intent_customers = set()

    target_customers = 0
    if STRATEGY_TARGET_CSV.is_file():
        try:
            target_customers = int(
                pd.read_csv(STRATEGY_TARGET_CSV, dtype={"customer_id": str})[
                    "customer_id"
                ].nunique()
            )
        except (OSError, ValueError, KeyError):
            target_customers = 0

    # 平台运营口径：全量客户均为运营对象；2,000 仅用于官方 A2 判分
    total_customers = 0
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM ods_customer")
                total_customers = int(cursor.fetchone()["count"])
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        total_customers = 0

    conversion_target = 30
    return {
        "conversion": {
            "actual": manager_responded,
            "target": conversion_target,
            "gap": max(0, conversion_target - manager_responded),
            "label": "经理 MGR001 4月转化",
        },
        "touch": {
            "total_customers": total_customers,
            "sent_customers": len(sent_customers),
            "official_target_customers": target_customers,
            "sent_strategies": sent_strategies,
            "total_strategies": int(len(strategy_channels)),
            "high_intent_untouched": len(high_intent_customers - sent_customers),
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


def _expiry_warning() -> dict:
    """到期预警：未来 30 天固定期限持仓到期（再配置/挽留机会）。

    口径：maturity = buy_date + duration_days，窗口 = 策略日次日至 +30 天。
    """
    from datetime import date, timedelta

    as_of = date(2026, 4, 15)
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


def _opportunity() -> dict:
    """转化机会挖掘：从预测与事件中挖出可即刻促转化的机会。

    - golden：高意向（≥70%）未触达客户 + 期望响应数（Σ 客户最高概率）
    - products：产品机会榜（高意向未触达触达记录按产品聚合 Top3）
    - expiry：到期承接窗口（来自 _expiry_warning）
    """
    import pandas as pd

    # 已触达客户集合
    sent_customers: set[str] = set()
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT SUBSTRING_INDEX(strategy_id, ':', 1) "
                    "AS customer_id FROM app_campaign_event "
                    "WHERE event_type = 'sent'"
                )
                sent_customers = {
                    str(row["customer_id"]) for row in cursor.fetchall()
                }
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        sent_customers = set()

    golden = {"count": 0, "expected_responses": 0}
    product_opportunity: list[dict] = []
    try:
        contacts = pd.read_csv(TEST_CONTACTS_CSV, dtype={"contact_id": str, "customer_id": str, "product_id": str})
        predictions = pd.read_csv(PREDICTION_CSV, dtype={"contact_id": str})
        merged = contacts.merge(predictions, on="contact_id", how="left")
        merged["response_prob"] = pd.to_numeric(merged["response_prob"], errors="coerce")
        high = merged[merged["response_prob"] >= 0.7]
        untouched = high[~high["customer_id"].isin(sent_customers)]

        # 客户级：取每人最高概率，期望响应 = Σ 概率
        best = (
            untouched.groupby("customer_id")["response_prob"].max()
        )
        golden = {
            "count": int(len(best)),
            "expected_responses": int(round(float(best.sum()))),
        }

        # 触达级：按产品聚合高意向未触达记录数
        counts = untouched.groupby("product_id")["contact_id"].count()
        product_opportunity = [
            {
                "product_id": str(product_id),
                "count": int(count),
            }
            for product_id, count in counts.sort_values(ascending=False).head(3).items()
        ]
    except (OSError, ValueError, KeyError):
        golden = {"count": 0, "expected_responses": 0}
        product_opportunity = []

    return {
        "golden": golden,
        "products": product_opportunity,
        "expiry": _expiry_warning(),
    }


def get_dashboard_overview(*, scenario_id: str | None = None) -> dict:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM ods_customer) AS customer_count,
                        (SELECT COALESCE(SUM(aum), 0) FROM ods_customer) AS total_aum,
                        (SELECT COUNT(*) FROM ods_product) AS product_count,
                        (SELECT COALESCE(SUM(amount), 0) FROM ods_holding)
                            AS total_holding_amount,
                        (SELECT COUNT(*) FROM ods_campaign)
                            AS historical_contact_count,
                        (SELECT COALESCE(AVG(responded), 0) FROM ods_campaign)
                            AS historical_response_rate
                    """
                )
                metrics = cursor.fetchone()
                cursor.execute(
                    "SELECT risk_appetite, COUNT(*) AS customer_count "
                    "FROM ods_customer GROUP BY risk_appetite"
                )
                risk_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT p.product_type, COALESCE(SUM(h.amount), 0) AS holding_amount
                    FROM ods_holding h
                    JOIN ods_product p ON p.product_id = h.product_id
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
            "historical_contact_count": int(metrics["historical_contact_count"]),
            "historical_response_rate": round(float(metrics["historical_response_rate"]), 4),
            "marketing_status": "READY",
        },
        "risk_distribution": build_risk_distribution(risk_rows),
        "holding_distribution": build_holding_distribution(
            holding_rows, total_holding_amount
        ),
        "a1_performance": _a1_performance(),
        "a2_performance": _a2_performance(),
        "portfolio_summary": _portfolio_summary(),
        "portfolio": _portfolio_performance(scenario_id),
        "marketing_funnel": _marketing_funnel(),
        "action_items": _action_items(),
        "expiry_warning": _expiry_warning(),
        "opportunity": _opportunity(),
    }


def get_dashboard_portfolio(scenario_id: str) -> dict:
    return _portfolio_performance(scenario_id)


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


@dashboard_bp.get("/overview")
def dashboard_overview():
    return success(get_dashboard_overview(scenario_id=_optional_scenario_id()))


@dashboard_bp.get("/portfolio")
def dashboard_portfolio():
    scenario_id = _optional_scenario_id()
    if scenario_id is None:
        raise ValidationError("scenario_id is required")
    return success(get_dashboard_portfolio(scenario_id))


@dashboard_bp.errorhandler(ValidationError)
def handle_validation_error(exc):
    return jsonify({"code": 400, "message": str(exc), "data": None}), 400


@dashboard_bp.errorhandler(ServiceError)
def handle_service_error(exc):
    return jsonify({"code": 503, "message": str(exc), "data": None}), 503
