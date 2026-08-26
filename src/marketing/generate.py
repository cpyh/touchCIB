"""单客户策略实时生成（运营干预：调 w_cf / manager 配额 → 重跑 Top3）。

设计（docs/demo-design.md）：
- 纯计算、不落库：读 CSV 快照 → 引擎生成 → 返回 JSON；
- 干预结果不进提交文件（提交 CSV 仍由离线管线生成）；
- 与 GET /customers/<id>/strategies（当前提交版）并排对比，展示联动效果。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

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
    StrategyRequest,
)
from .pipeline import generate_strategies

PROJECT_DIR = Path(__file__).resolve().parents[2]


class StrategyGenerationError(ValueError):
    """生成请求不合法（客户不存在 / 不在目标名单）。"""


@lru_cache(maxsize=1)
def _generation_context():
    """装载生成所需全部输入（进程内缓存一次）。"""
    raw = PROJECT_DIR / "src" / "data" / "raw"
    customers = load_customers(raw / "t_customer.csv")
    products = load_products(raw / "t_product.csv")
    strategy_dates = load_strategy_customers(
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
    behaviors = build_behaviors(customers, events, holdings, strategy_dates)

    as_of = max(strategy_dates.values())
    similarity = build_co_holding_similarity(holdings, as_of=as_of)
    cf_scores = customer_cf_scores(
        similarity,
        {
            customer_id: behavior.holding_product_ids
            for customer_id, behavior in behaviors.items()
        },
        [product.product_id for product in products],
    )
    return customers, products, strategy_dates, behaviors, model_scores, cf_scores


def generate_customer_strategy(
    customer_id: str,
    *,
    w_cf: float = DEFAULT_W_CF,
    manager_quota: int = DEFAULT_MANAGER_QUOTA,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """为单个客户现场生成 Top N 策略（含轨迹与信号分解），不落库。"""
    if not 0.0 <= w_cf <= 1.0:
        raise ValueError("w_cf must be in [0, 1]")
    if manager_quota < 0:
        raise ValueError("manager_quota must be >= 0")
    if not 1 <= top_n <= 30:
        raise ValueError("top_n must be between 1 and 30")

    customers, products, strategy_dates, behaviors, model_scores, cf_scores = (
        _generation_context()
    )
    customer = customers.get(customer_id)
    if customer is None:
        raise StrategyGenerationError(f"客户 {customer_id} 不存在")
    strategy_date = strategy_dates.get(customer_id)
    if strategy_date is None:
        raise StrategyGenerationError(
            f"客户 {customer_id} 不在 A2 目标名单（2000 客户）"
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
        "parameters": {
            "w_cf": w_cf,
            "manager_quota": manager_quota,
            "top_n": top_n,
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
