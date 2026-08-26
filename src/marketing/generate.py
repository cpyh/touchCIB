"""全量客户单客策略计算（运营干预：调 w_cf / manager 配额 → 重跑 Top3）。

设计（docs/demo-design.md）：
- 纯计算、不落库：读 CSV 快照 → 引擎生成 → 返回 JSON；
- 干预结果不进提交文件（提交 CSV 仍由离线管线生成）；
- 与 GET /customers/<id>/strategies（正式版或已冻结实时版）并排对比。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from ..partA1serving.feature_service import PredictRequest
from .collaborative import (
    build_co_holding_similarity,
    customer_cf_scores,
)
from .io import (
    build_behaviors,
    load_customers,
    load_model_scores,
    load_products,
    load_strategy_customers,
)
from .models import (
    DEFAULT_MANAGER_QUOTA,
    DEFAULT_TOP_N,
    DEFAULT_W_CF,
    MANAGER_ELIGIBLE_AUM,
    MANAGER_ELIGIBLE_VIP,
    StrategyRequest,
)
from .pipeline import generate_strategies

PROJECT_DIR = Path(__file__).resolve().parents[2]

if TYPE_CHECKING:
    from ..partA1serving.predictor import ResponsePredictor


class StrategyGenerationError(ValueError):
    """生成请求不合法（客户不存在或参数不合法）。"""


@lru_cache(maxsize=1)
def _generation_context():
    """装载生成所需全部输入（进程内缓存一次）。"""
    raw = PROJECT_DIR / "src" / "data" / "raw"
    customers = load_customers(raw / "t_customer.csv")
    products = load_products(raw / "t_product.csv")
    official_strategy_dates = load_strategy_customers(
        raw / "partA_strategy_customers.csv"
    )
    events = pd.read_csv(raw / "t_event.csv", dtype={"customer_id": str})
    holdings = pd.read_csv(
        raw / "t_holding.csv",
        dtype={"customer_id": str, "product_id": str},
    )
    model_scores = load_model_scores(
        raw / "partA_test_contacts.csv",
        PROJECT_DIR / "partA_prediction.csv",
    )
    activity_date = max(official_strategy_dates.values())
    # 赛事只为2000位A2目标客户提供strategy_date。平台实时策略面向全量客户，
    # 非A2客户使用当前活动日期，并保持相同的as-of截断口径。
    strategy_dates = {
        customer_id: official_strategy_dates.get(customer_id, activity_date)
        for customer_id in customers
    }
    behaviors = build_behaviors(customers, events, holdings, strategy_dates)

    similarity = build_co_holding_similarity(holdings, as_of=activity_date)
    cf_scores = customer_cf_scores(
        similarity,
        {
            customer_id: behavior.holding_product_ids
            for customer_id, behavior in behaviors.items()
        },
        [product.product_id for product in products],
    )
    return (
        customers,
        products,
        strategy_dates,
        frozenset(official_strategy_dates),
        behaviors,
        model_scores,
        cf_scores,
    )


def _eligible_prediction_channels(customer, behavior, manager_quota: int) -> list[str]:
    """返回规则引擎实际可能采用的渠道，用于把A1渠道概率边际化成产品分数。"""
    channels = ["sms"]
    if behavior.complaint_count_90d < 2:
        channels.append("call")
    if customer.has_app:
        channels.append("app_push")
    if manager_quota > 0 and (
        customer.vip_level in MANAGER_ELIGIBLE_VIP
        or customer.aum >= MANAGER_ELIGIBLE_AUM
    ):
        channels.append("manager")
    return channels


def _live_model_scores(
    predictor: "ResponsePredictor",
    *,
    customer,
    behavior,
    strategy_date,
    product_ids: list[str],
    manager_quota: int,
) -> dict[tuple[str, str], float]:
    """为单客户完整计算30个产品的A1概率，不再受测试名单稀疏覆盖限制。"""
    channels = _eligible_prediction_channels(customer, behavior, manager_quota)
    requests = [
        PredictRequest(
            customer_id=customer.customer_id,
            product_id=product_id,
            channel=channel,
            contact_date=strategy_date.isoformat(),
        )
        for product_id in product_ids
        for channel in channels
    ]
    predictions = predictor.predict_batch(requests)
    totals = {product_id: 0.0 for product_id in product_ids}
    counts = {product_id: 0 for product_id in product_ids}
    for prediction in predictions:
        totals[prediction.product_id] += prediction.probability
        counts[prediction.product_id] += 1
    return {
        (customer.customer_id, product_id): totals[product_id] / counts[product_id]
        for product_id in product_ids
    }


def generate_customer_strategy(
    customer_id: str,
    *,
    w_cf: float = DEFAULT_W_CF,
    manager_quota: int = DEFAULT_MANAGER_QUOTA,
    top_n: int = DEFAULT_TOP_N,
    response_predictor: "ResponsePredictor | None" = None,
) -> dict:
    """为单个客户现场生成 Top N 策略（含轨迹与信号分解），不落库。"""
    if not 0.0 <= w_cf <= 1.0:
        raise ValueError("w_cf must be in [0, 1]")
    if manager_quota < 0:
        raise ValueError("manager_quota must be >= 0")
    if not 1 <= top_n <= 30:
        raise ValueError("top_n must be between 1 and 30")

    (
        customers,
        products,
        strategy_dates,
        official_customer_ids,
        behaviors,
        snapshot_model_scores,
        cf_scores,
    ) = _generation_context()
    customer = customers.get(customer_id)
    if customer is None:
        raise StrategyGenerationError(f"客户 {customer_id} 不存在")
    strategy_date = strategy_dates.get(customer_id)

    model_scores = snapshot_model_scores
    if response_predictor is not None:
        model_scores = _live_model_scores(
            response_predictor,
            customer=customer,
            behavior=behaviors[customer_id],
            strategy_date=strategy_date,
            product_ids=[product.product_id for product in products],
            manager_quota=manager_quota,
        )

    product_map = {product.product_id: product for product in products}
    request = StrategyRequest(
        customer=customer,
        strategy_date=strategy_date,
        behavior=behaviors[customer_id],
        top_n=top_n,
    )
    (result,) = generate_strategies(
        [request],
        products,
        model_scores=model_scores,
        cf_scores=cf_scores,
        w_cf=w_cf,
        manager_quota=manager_quota,
    )

    return {
        "customer_id": customer_id,
        "strategy_date": strategy_date.isoformat(),
        "official_target": customer_id in official_customer_ids,
        "strategy_source": "live_generated",
        "risk_appetite": customer.risk_appetite,
        "vip_level": customer.vip_level,
        "aum": round(float(customer.aum), 2),
        "parameters": {
            "w_cf": w_cf,
            "manager_quota": manager_quota,
            "top_n": top_n,
            "a1_source": "mysql_serving" if response_predictor is not None else "submission_snapshot",
        },
        "steps": [
            {"step": step.step, "summary": step.summary, "details": list(step.details)}
            for step in result.steps
        ],
        "items": [
            {
                "rank": item.rank,
                "product_id": item.product_id,
                "product_name": product_map[item.product_id].product_name,
                "risk_level": product_map[item.product_id].risk_level,
                "expected_return": round(
                    float(product_map[item.product_id].expected_return), 4
                ),
                "product_type": product_map[item.product_id].product_type,
                "recommended_channel": item.recommended_channel,
                "recommended_time": item.recommended_time,
                "marketing_script": item.marketing_script,
                "score": round(item.score, 8),
                "model_prob": round(item.model_prob, 8),
                "cf_score": round(item.cf_score, 8),
                "overshoot": item.overshoot,
                "rule_trace": [
                    {
                        "rule_id": outcome.rule_id,
                        "passed": outcome.passed,
                        "reason": outcome.reason,
                    }
                    for outcome in item.rule_trace
                ],
            }
            for item in result.items
        ],
    }
