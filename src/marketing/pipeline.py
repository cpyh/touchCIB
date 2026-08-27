"""A2 基础规则与策略装配组件。

正式提交和业务日批统一由 ``marketing.batch`` 负责完整 A1 评分；本模块保留
规则装配的纯内存组件、渠道/时段决策函数及可单测的数据结构，不再读取 A1/A2
提交 CSV，也不再提供独立命令行生成路径。

规则装配阶段一（全局批次）：
    产品排序 = A1 响应概率；
    合规顺位过滤（风险偏好内优先，不足 3 个时自动溢出 1 级）；
    当日画像动态生成经理池，池外客户由静态画像规则分流渠道。
阶段二（逐客户）：
    单客户统一执行渠道 → 时段（职业×渠道偏好序）→ 话术 → 规则回验。

全部确定性执行（排序 tie-break 用 product_id / customer_id），无需随机数。
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from .engine import RuleEngine
from .channel_policy import build_channel_decisions, resolve_manager_pool_size
from .models import (
    ChannelDecision,
    DEFAULT_MANAGER_QUOTA,
    RISK_RANK,
    TIME_SLOTS,
    Product,
    StepRecord,
    StrategyItem,
    StrategyRequest,
    StrategyResult,
)
from .rules import build_default_engine
from .templates import build_script

DEFAULT_SLOT_ORDER = [
    "工作日09:00-12:00",
    "工作日12:00-14:00",
    "工作日18:00-21:00",
    "周末09:00-12:00",
    "周末14:00-18:00",
]

OCCUPATION_SLOT_ORDER = {
    "退休": [
        "工作日09:00-12:00",
        "工作日12:00-14:00",
        "周末09:00-12:00",
        "工作日18:00-21:00",
        "周末14:00-18:00",
    ],
    "个体经营": [
        "工作日12:00-14:00",
        "周末14:00-18:00",
        "工作日18:00-21:00",
        "工作日09:00-12:00",
        "周末09:00-12:00",
    ],
    "公务员": [
        "工作日12:00-14:00",
        "工作日18:00-21:00",
        "周末14:00-18:00",
        "工作日09:00-12:00",
        "周末09:00-12:00",
    ],
    "企业职员": [
        "工作日18:00-21:00",
        "周末14:00-18:00",
        "周末09:00-12:00",
        "工作日12:00-14:00",
        "工作日09:00-12:00",
    ],
    "专业技术": [
        "工作日18:00-21:00",
        "周末09:00-12:00",
        "周末14:00-18:00",
        "工作日12:00-14:00",
        "工作日09:00-12:00",
    ],
    "其他": DEFAULT_SLOT_ORDER,
}

CHANNEL_SLOT_ORDER = {
    "call": [
        "工作日09:00-12:00",
        "工作日12:00-14:00",
        "工作日18:00-21:00",
        "周末14:00-18:00",
        "周末09:00-12:00",
    ],
    "app_push": [
        "工作日18:00-21:00",
        "工作日12:00-14:00",
        "周末09:00-12:00",
        "周末14:00-18:00",
        "工作日09:00-12:00",
    ],
    "manager": [
        "工作日09:00-12:00",
        "工作日12:00-14:00",
        "工作日18:00-21:00",
        "周末14:00-18:00",
        "周末09:00-12:00",
    ],
    "sms": [
        "工作日09:00-12:00",
        "工作日12:00-14:00",
        "工作日18:00-21:00",
        "周末09:00-12:00",
        "周末14:00-18:00",
    ],
}

_AGED_GROUPS = ("55-64", "65+")


# ----------------------------------------------------------------
# 打分与候选
# ----------------------------------------------------------------


def _model_probability(
    customer_id: str,
    product: Product,
    model_scores: Mapping[tuple[str, str], float],
) -> float:
    model_prob = float(model_scores.get((customer_id, product.product_id), 0.0))
    if not 0.0 <= model_prob <= 1.0:
        raise ValueError(
            f"model score out of [0,1] for {customer_id}/{product.product_id}"
        )
    return model_prob


def _compliance_evaluate(
    engine: RuleEngine,
    strategy_date: date,
    products: Sequence[Product],
    max_allowed_risk: int,
    customer,
) -> tuple[list[Product], list[str]]:
    passed: list[Product] = []
    blocked: list[str] = []
    for product in products:
        context = {
            "customer": customer,
            "product": product,
            "strategy_date": strategy_date,
            "max_allowed_risk": max_allowed_risk,
        }
        outcomes = engine.evaluate_all(context, categories=("compliance",))
        failures = [o for o in outcomes if not o.passed]
        if failures:
            blocked.append(
                f"{product.product_id}: {'; '.join(o.reason for o in failures)}"
            )
        else:
            passed.append(product)
    return passed, blocked


def _select_top(
    customer_id: str,
    compliant: Sequence[Product],
    overshoot_pool: Sequence[Product],
    top_n: int,
    model_scores: Mapping[tuple[str, str], float],
) -> list[tuple[Product, float, bool]]:
    def score_sort(pool: Sequence[Product]) -> list[tuple[Product, float]]:
        scored = [
            (product, _model_probability(customer_id, product, model_scores))
            for product in pool
        ]
        scored.sort(key=lambda entry: (-entry[1], entry[0].product_id))
        return scored

    selected: list[tuple[Product, float, bool]] = [
        (*entry, False) for entry in score_sort(compliant)[:top_n]
    ]
    if len(selected) < top_n:
        remaining = top_n - len(selected)
        selected.extend(
            (*entry, True) for entry in score_sort(overshoot_pool)[:remaining]
        )
    return selected


# ----------------------------------------------------------------
# 渠道与时段
# ----------------------------------------------------------------


def _channel_ladder(customer, behavior) -> list[str]:
    ladder: list[str] = ["manager"]
    if customer.has_app:
        ladder.append("app_push")
    if behavior.complaint_count_90d < 2:
        ladder.append("call")
    ladder.append("sms")
    return ladder


def _slot_order(customer, channel: str) -> list[str]:
    order = list(OCCUPATION_SLOT_ORDER.get(customer.occupation, DEFAULT_SLOT_ORDER))
    for slot in CHANNEL_SLOT_ORDER.get(channel, DEFAULT_SLOT_ORDER):
        if slot not in order:
            order.append(slot)
    for slot in TIME_SLOTS:
        if slot not in order:
            order.append(slot)
    if customer.age_group in _AGED_GROUPS:
        order = ["工作日09:00-12:00"] + [
            slot for slot in order if slot != "工作日09:00-12:00"
        ]
    return order


# ----------------------------------------------------------------
# 阶段二：单客户生成
# ----------------------------------------------------------------


def _plan_customer(
    request: StrategyRequest,
    products: Sequence[Product],
    engine: RuleEngine,
    model_scores: Mapping[tuple[str, str], float],
    channel_decision: ChannelDecision,
    manager_pool_size: int,
) -> StrategyResult:
    customer = request.customer
    behavior = request.effective_behavior()
    base_rank = RISK_RANK[customer.risk_appetite]
    steps: list[StepRecord] = []

    # ---- Step 2 合规过滤（先合规池，不足时溢出 1 级） ----
    compliant, blocked_details = _compliance_evaluate(
        engine, request.strategy_date, products,
        max_allowed_risk=base_rank, customer=customer,
    )
    overshoot_pool: list[Product] = []
    overshoot = 0
    if len(compliant) < request.top_n:
        overshoot = 1
        overshoot_pool, _ = _compliance_evaluate(
            engine, request.strategy_date, products,
            max_allowed_risk=base_rank + 1, customer=customer,
        )
        overshoot_pool = [p for p in overshoot_pool if p not in compliant]
        if len(compliant) + len(overshoot_pool) < request.top_n:
            raise RuntimeError(
                f"{customer.customer_id}: 合规+溢出候选不足 {request.top_n} 个"
            )
        steps.append(
            StepRecord(
                "compliance_filter",
                f"风险偏好内产品 {len(compliant)} 个 < {request.top_n}，"
                f"自动溢出 1 级补充 {len(overshoot_pool)} 个候选",
                tuple(blocked_details),
            )
        )
    else:
        steps.append(
            StepRecord(
                "compliance_filter",
                f"{len(products)} 个产品 → 合规池 {len(compliant)} 个",
                tuple(blocked_details),
            )
        )

    # ---- Step 3/4 打分排序选 Top N ----
    selected = _select_top(
        customer.customer_id, compliant, overshoot_pool, request.top_n,
        model_scores,
    )
    steps.append(
        StepRecord(
            "ranking",
            f"Top{len(selected)} 排序完成（A1 响应概率）",
            tuple(
                f"{product.product_id}: probability={model_prob:.6f}"
                for product, model_prob, _ in selected
            ),
        )
    )

    # ---- Step 5/6/7 渠道 → 时段 → 话术 ----
    items: list[StrategyItem] = []
    channel_details: list[str] = []
    slot_details: list[str] = []
    for position, (product, model_prob, is_overshoot) in enumerate(
        selected, start=1
    ):
        rank = position
        channel = channel_decision.assigned_channel
        reason = channel_decision.reason
        channel_details.append(f"rank{rank}: {channel}（{reason}）")

        slots = _slot_order(customer, channel)
        slot = slots[min(position - 1, len(slots) - 1)]
        slot_details.append(
            f"rank{rank}: {slot}（职业={customer.occupation}，渠道={channel}"
            + ("，年龄 55+ 前置上午" if customer.age_group in _AGED_GROUPS else "")
            + "）"
        )

        script = build_script(
            customer, product, channel, overshoot=is_overshoot
        )

        context = {
            "customer": customer,
            "behavior": behavior,
            "product": product,
            "channel": channel,
            "recommended_time": slot,
            "marketing_script": script,
            "overshoot": is_overshoot,
            "manager_eligible": channel_decision.manager_eligible,
            "manager_pool_member": channel_decision.manager_pool_member,
            "manager_priority_rank": channel_decision.manager_priority_rank,
            "manager_pool_size": manager_pool_size,
        }
        trace = engine.evaluate_all(
            context, categories=("channel", "timing", "script")
        )
        failures = [outcome for outcome in trace if not outcome.passed]
        if failures:
            raise RuntimeError(
                f"{customer.customer_id} rank{rank}: "
                + "; ".join(o.reason for o in failures)
            )

        items.append(
            StrategyItem(
                rank=rank,
                product_id=product.product_id,
                recommended_channel=channel,
                recommended_time=slot,
                marketing_script=script,
                model_prob=model_prob,
                overshoot=is_overshoot,
                rule_trace=tuple(trace),
            )
        )

    steps.append(
        StepRecord(
            "channel_selection",
            f"{len(items)} 条渠道分配完成",
            tuple(channel_details),
        )
    )
    steps.append(
        StepRecord("slot_selection", "时段推荐完成", tuple(slot_details))
    )
    steps.append(
        StepRecord(
            "script_generation",
            f"{len(items)} 条话术生成（含合规提示语"
            f"{'与溢出风险提示' if overshoot else ''}）",
        )
    )
    steps.append(StepRecord("validation", f"{len(items)} 条策略全部通过规则回验"))

    return StrategyResult(
        customer_id=customer.customer_id,
        strategy_date=request.strategy_date,
        items=tuple(items),
        steps=tuple(steps),
    )


# ----------------------------------------------------------------
# 批次入口
# ----------------------------------------------------------------


def generate_strategies(
    requests: Sequence[StrategyRequest],
    products: Sequence[Product],
    *,
    model_scores: Mapping[tuple[str, str], float] | None = None,
    manager_quota: int | None = DEFAULT_MANAGER_QUOTA,
    manager_pool_size: int | None = None,
    engine: RuleEngine | None = None,
) -> list[StrategyResult]:
    """按 A1 概率排序并应用规则，生成客户 Top N 策略。"""
    if not requests or not products:
        raise ValueError("requests and products must not be empty")
    product_ids = [p.product_id for p in products]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("duplicate product_id in product pool")
    engine = engine or build_default_engine()
    model_scores = model_scores or {}
    effective_pool_size = resolve_manager_pool_size(
        manager_pool_size, manager_quota
    )
    customers = {request.customer.customer_id: request.customer for request in requests}
    behaviors = {
        request.customer.customer_id: request.effective_behavior()
        for request in requests
    }
    channel_decisions = build_channel_decisions(
        customers,
        behaviors,
        manager_pool_size=effective_pool_size,
    )

    results: list[StrategyResult] = []
    for request in requests:
        results.append(
            _plan_customer(
                request,
                products,
                engine,
                model_scores,
                channel_decisions[request.customer.customer_id],
                effective_pool_size,
            )
        )
    return results
