"""单客户策略试算：复用正式日批的 A1排序+A2规则逻辑，不读取CSV。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING

from ..business_date import DEFAULT_BUSINESS_DATE
from .batch import (
    RULE_VERSION,
    compute_marketing_batch,
    eligible_business_channels,
)
from .models import DEFAULT_MANAGER_QUOTA, DEFAULT_TOP_N
from .rules import TOGGLEABLE_CONSTRAINT_IDS, normalize_disabled_constraints
from .warehouse import load_marketing_context

if TYPE_CHECKING:
    from ..partA1serving.predictor import ResponsePredictor


class StrategyGenerationError(ValueError):
    """生成请求不合法（客户不存在或参数不合法）。"""


def generate_customer_strategy(
    customer_id: str,
    *,
    manager_quota: int = DEFAULT_MANAGER_QUOTA,
    top_n: int = DEFAULT_TOP_N,
    disabled_constraints: Iterable[str] = (),
    response_predictor: "ResponsePredictor | None" = None,
    strategy_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    """从MySQL DWD现场试算单客户Top3；结果仅返回，不覆盖正式ADS批次。"""
    normalized = customer_id.strip().upper()
    if not normalized:
        raise StrategyGenerationError("customer_id 不能为空")
    if not 1 <= top_n <= 3:
        raise ValueError("top_n must be between 1 and 3")
    disabled = normalize_disabled_constraints(disabled_constraints)
    if response_predictor is None:
        from ..partA1serving.runtime import get_mysql_predictor

        response_predictor = get_mysql_predictor()

    try:
        context = load_marketing_context(
            strategy_date,
            customer_ids=[normalized],
        )
    except ValueError as exc:
        raise StrategyGenerationError(str(exc)) from exc

    result = compute_marketing_batch(
        context,
        response_predictor,
        batch_id=f"preview_{normalized}_{strategy_date:%Y%m%d}",
        manager_quota=manager_quota,
        disabled_constraints=disabled,
    )
    customer = context.customers[normalized]
    evaluated_channels = eligible_business_channels(
        customer,
        context.behaviors[normalized],
        disabled_constraints=disabled,
    )
    baseline_channels = eligible_business_channels(
        customer,
        context.behaviors[normalized],
    )
    product_map = {product.product_id: product for product in context.products}
    items = []
    for row in result.strategy_rows[:top_n]:
        product = product_map[row[4]]
        items.append(
            {
                "rank": int(row[2]),
                "product_id": row[4],
                "product_name": product.product_name,
                "risk_level": product.risk_level,
                "expected_return": round(product.expected_return, 6),
                "product_type": product.product_type,
                "recommended_channel": row[5],
                "recommended_time": row[6],
                "marketing_script": row[7],
                "model_prob": round(float(row[8]), 8),
                "a1_rank": int(row[9]),
                "selection_reason": row[11],
                "rule_trace": json.loads(row[10]),
            }
        )

    passed_count = sum(1 for row in result.decision_rows if int(row[6]) == 1)
    return {
        "customer_id": normalized,
        "strategy_date": strategy_date.isoformat(),
        "strategy_source": "live_preview",
        "risk_appetite": customer.risk_appetite,
        "vip_level": customer.vip_level,
        "aum": round(customer.aum, 2),
        "parameters": {
            "manager_quota": manager_quota,
            "manager_quota_effective": False,
            "top_n": top_n,
            "disabled_constraints": sorted(disabled),
            "constraints": {
                rule_id: rule_id not in disabled
                for rule_id in sorted(TOGGLEABLE_CONSTRAINT_IDS)
            },
            "evaluated_channels": list(evaluated_channels),
            "baseline_channels": list(baseline_channels),
            "a1_candidate_count": len(context.products) * len(evaluated_channels),
            "baseline_candidate_count": len(context.products) * len(baseline_channels),
            "ranking_source": "a1_probability",
            "a1_source": "mysql_dwd_online",
            "rule_version": RULE_VERSION,
        },
        "steps": [
            {
                "step": "a1_ranking",
                "summary": (
                    f"A1完成{len(context.products)}个产品×"
                    f"{len(evaluated_channels)}个候选渠道评分"
                ),
                "details": [],
            },
            {
                "step": "a2_rule_filter",
                "summary": f"基础规则过滤后保留{passed_count}个候选",
                "details": [],
            },
            {
                "step": "top3",
                "summary": f"按A1概率生成Top{len(items)}",
                "details": [item["selection_reason"] for item in items],
            },
        ],
        "items": items,
    }
