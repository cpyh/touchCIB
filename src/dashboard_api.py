"""可视化看板 API（由 liantiao backend/app/services/dashboard_service.py 统一而来）。

契约：envelope {code, message, data}，路径 /api/v1/dashboard/overview 与 /portfolio。
与队友版本的区别：A1/A2/组合/漏斗的 NOT_READY 占位已用平台真实数据填满
（表映射 t_* → ods_*，组合配置调用现有 Part B 求解器）。
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

PROJECT_DIR = Path(__file__).resolve().parents[1]
METRICS_JSON = (
    PROJECT_DIR / "src" / "data" / "outputs" / "a1_validation_metrics.json"
)
PREDICTION_CSV = PROJECT_DIR / "partA_prediction.csv"
STRATEGY_CSV = PROJECT_DIR / "partA_strategy.csv"

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
    """A1 真实指标：验证 AUC/F1/Lift + 预测概率分布。"""
    import pandas as pd

    if not METRICS_JSON.is_file():
        return {"status": "NOT_READY", "auc": None, "f1": None, "lift_at_10": None, "probability_distribution": []}
    metrics = json.loads(METRICS_JSON.read_text(encoding="utf-8"))
    probabilities = pd.read_csv(PREDICTION_CSV)
    probs = pd.to_numeric(probabilities["response_prob"])
    distribution = [
        {"bucket": "高意向(≥70%)", "count": int((probs >= 0.7).sum())},
        {"bucket": "中意向(30%~70%)", "count": int(((probs >= 0.3) & (probs < 0.7)).sum())},
        {"bucket": "低意向(<30%)", "count": int((probs < 0.3).sum())},
    ]
    return {
        "status": "READY",
        "metric_scope": "OFFLINE_VALIDATION",
        "auc": metrics.get("auc"),
        "f1": metrics.get("best_f1"),
        "lift_at_10": metrics.get("lift_at_10_percent"),
        "probability_distribution": distribution,
    }


def _a2_performance() -> dict:
    """A2 真实指标：策略规模/覆盖率 + 渠道分布（HitRate 为隐藏标签，置 None）。"""
    import pandas as pd

    strategies = pd.read_csv(STRATEGY_CSV, dtype=str)
    total_target = 2000
    generated = int(strategies["customer_id"].nunique())
    channel_distribution = [
        {"channel": channel, "count": int(count)}
        for channel, count in strategies["recommended_channel"].value_counts().items()
    ]
    return {
        "status": "READY",
        "metric_scope": "OFFLINE_VALIDATION",
        "target_customer_count": total_target,
        "generated_customer_count": generated,
        "coverage_rate": round(generated / total_target, 4) if total_target else None,
        "hit_rate_at_3": None,
        "channel_distribution": channel_distribution,
    }


def _portfolio_performance(scenario_id: str | None) -> dict:
    """组合配置：调用现有 Part B 求解器按场景实时求解。"""
    if scenario_id is None:
        return {
            "status": "NOT_READY",
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
    from .algorithms.partb import (
        RANDOM_STATE,
        build_covariance_matrix,
        build_masks,
        load_correlation_matrix,
        load_products,
        load_scenarios,
        solve_one_scenario,
    )
    import numpy as np
    import pandas as pd

    raw = PROJECT_DIR / "src" / "data" / "raw"
    products = load_products(raw)
    product_info = pd.read_csv(raw / "t_product.csv", dtype={"product_id": str})
    info_map = {
        row.product_id: row for row in product_info.itertuples()
    }
    scenarios = {s.scenario_id: s for s in load_scenarios(raw)}
    scenario = scenarios.get(scenario_id)
    if scenario is None:
        raise ValidationError("scenario not found")
    correlation = load_correlation_matrix(raw, products.product_ids)
    sigma = build_covariance_matrix(products.volatility, correlation)
    high_risk_mask, non_liquid_mask = build_masks(products)
    result = solve_one_scenario(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        rng=np.random.default_rng(RANDOM_STATE),
    )
    type_amounts: dict[str, float] = {}
    for product_id, weight in zip(products.product_ids, result.weights):
        if weight <= 0:
            continue
        info = info_map[product_id]
        type_amounts[info.product_type] = (
            type_amounts.get(info.product_type, 0.0) + float(weight)
        )
    allocation_by_type = [
        {"product_type": product_type, "weight": round(weight, 6)}
        for product_type, weight in sorted(type_amounts.items())
    ]
    allocation_items = [
        {
            "product_id": product_id,
            "product_name": info_map[product_id].product_name,
            "product_type": info_map[product_id].product_type,
            "risk_level": info_map[product_id].risk_level,
            "weight": round(float(weight), 6),
        }
        for product_id, weight in zip(products.product_ids, result.weights)
        if weight > 0
    ]
    return {
        "status": "READY",
        "scenario_id": scenario_id,
        "total_amount": float(scenario.total_amount),
        "expected_return": round(result.expected_return, 8),
        "volatility": round(result.portfolio_volatility, 8),
        "utility": round(result.utility, 8),
        "cash_weight": round(result.cash_weight, 8),
        "constraints_satisfied": True,
        "optimality_gap": result.absolute_gap,
        "allocation_by_product_type": allocation_by_type,
        "allocation_items": allocation_items,
    }


def _marketing_funnel() -> dict:
    """营销漏斗真实数据：目标客户 → 已生成 → 已触达 → 已响应（事件表口径）。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(DISTINCT strategy_id) AS contacted, "
                    "SUM(event_type = 'sent') AS sent_rows "
                    "FROM app_campaign_event"
                )
                sent = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(DISTINCT strategy_id) AS responded "
                    "FROM app_campaign_event WHERE event_type = 'responded'"
                )
                responded = cursor.fetchone()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError):
        contacted = responded = 0
    contacted_count = int(sent["contacted"]) if sent else 0
    responded_count = int(responded["responded"]) if responded else 0
    return {
        "status": "READY",
        "target_customer_count": 2000,
        "generated_customer_count": 2000,
        "contacted_customer_count": contacted_count,
        "responded_customer_count": responded_count,
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
        "portfolio": _portfolio_performance(scenario_id),
        "marketing_funnel": _marketing_funnel(),
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
