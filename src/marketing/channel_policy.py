"""经理池日批与画像渠道策略。

该模块只依赖业务实体，不依赖模型或数据库，因此正式日批、单客试算和纯内存
策略组件可以复用同一套渠道决策。正式经理池由日批计算并写入 ADS 当日快照。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import (
    DEFAULT_MANAGER_POOL_SIZE,
    MANAGER_ELIGIBLE_AUM,
    MANAGER_ELIGIBLE_VIP,
    ChannelDecision,
    Customer,
    CustomerBehavior,
)
from .rules import normalize_disabled_constraints


def resolve_manager_pool_size(
    manager_pool_size: int | None,
    manager_quota: int | None,
    strategies_per_customer: int = 3,
) -> int:
    """将旧的策略行配额兼容转换为客户池人数。"""
    if strategies_per_customer <= 0:
        raise ValueError("strategies_per_customer must be positive")
    if manager_pool_size is None:
        manager_pool_size = (
            DEFAULT_MANAGER_POOL_SIZE
            if manager_quota is None
            else manager_quota // strategies_per_customer
        )
    if manager_pool_size < 0:
        raise ValueError("manager_pool_size must be non-negative")
    return int(manager_pool_size)


def manager_priority(
    customer: Customer,
    behavior: CustomerBehavior,
) -> tuple[bool, float, str]:
    """返回透明、可解释的高价值客户静态画像优先级。"""
    eligible = (
        customer.vip_level in MANAGER_ELIGIBLE_VIP
        or customer.aum >= MANAGER_ELIGIBLE_AUM
    )
    vip_points = {"钻石": 40.0, "金卡": 25.0}.get(customer.vip_level, 0.0)
    if customer.aum >= 2_000_000:
        aum_points = 25.0
    elif customer.aum >= 1_000_000:
        aum_points = 20.0
    elif customer.aum >= MANAGER_ELIGIBLE_AUM:
        aum_points = 12.0
    else:
        aum_points = 0.0
    consult_points = min(15.0, behavior.consult_count_90d * 5.0)
    login_points = min(10.0, behavior.login_count_30d * 1.0)
    holding_points = min(10.0, len(behavior.holding_product_ids) * 2.0)
    score = vip_points + aum_points + consult_points + login_points + holding_points
    reason = (
        f"VIP {vip_points:.0f} + AUM {aum_points:.0f} + "
        f"咨询 {consult_points:.0f} + 活跃 {login_points:.0f} + "
        f"持仓 {holding_points:.0f} = {score:.0f}"
    )
    return eligible, score, reason


def select_business_channel(
    customer: Customer,
    behavior: CustomerBehavior,
    *,
    manager_enabled: bool = True,
    disabled_constraints: Iterable[str] = (),
) -> str:
    """按经理池成员资格与客户画像选择唯一可执行渠道。"""
    if manager_enabled:
        return "manager"
    disabled = normalize_disabled_constraints(disabled_constraints)
    app_available = customer.has_app or "channel_app_requires_app" in disabled
    call_available = (
        behavior.complaint_count_90d < 2
        or "channel_call_complaint_block" in disabled
    )
    if app_available and behavior.login_count_30d > 0:
        return "app_push"
    if call_available and behavior.consult_count_90d > 0:
        return "call"
    if app_available:
        return "app_push"
    if call_available:
        return "call"
    return "sms"


def allocate_manager_customers(
    customers: Iterable[Customer],
    *,
    manager_pool_size: int | None = None,
    manager_quota: int | None = None,
    strategies_per_customer: int = 3,
    behaviors: Mapping[str, CustomerBehavior] | None = None,
) -> set[str]:
    """根据日批截至时点的最新画像选出经理候选池。"""
    size = resolve_manager_pool_size(
        manager_pool_size, manager_quota, strategies_per_customer
    )
    behavior_map = behaviors or {}
    ranked: list[tuple[float, float, str]] = []
    for customer in customers:
        behavior = behavior_map.get(
            customer.customer_id,
            CustomerBehavior(customer_id=customer.customer_id),
        )
        eligible, score, _ = manager_priority(customer, behavior)
        if eligible:
            ranked.append((score, customer.aum, customer.customer_id))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return {customer_id for _, _, customer_id in ranked[:size]}


def build_channel_decisions(
    customers: Mapping[str, Customer],
    behaviors: Mapping[str, CustomerBehavior],
    *,
    manager_pool_size: int | None = None,
    manager_quota: int | None = None,
    disabled_constraints: Iterable[str] = (),
) -> dict[str, ChannelDecision]:
    """一次性计算全客群当日渠道决策。"""
    size = resolve_manager_pool_size(manager_pool_size, manager_quota)
    scored: list[tuple[float, float, str]] = []
    score_by_customer: dict[str, tuple[bool, float, str]] = {}
    for customer_id, customer in customers.items():
        eligible, score, score_reason = manager_priority(
            customer, behaviors[customer_id]
        )
        score_by_customer[customer_id] = (eligible, score, score_reason)
        if eligible:
            scored.append((score, customer.aum, customer_id))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    pool_rank = {
        customer_id: rank
        for rank, (_, _, customer_id) in enumerate(scored[:size], start=1)
    }

    decisions: dict[str, ChannelDecision] = {}
    for customer_id in sorted(customers):
        customer = customers[customer_id]
        behavior = behaviors[customer_id]
        eligible, score, score_reason = score_by_customer[customer_id]
        rank = pool_rank.get(customer_id)
        pool_member = rank is not None
        channel = select_business_channel(
            customer,
            behavior,
            manager_enabled=pool_member,
            disabled_constraints=disabled_constraints,
        )
        if pool_member:
            reason = f"进入当日高价值经理池（第 {rank}/{size} 位）；{score_reason}"
        elif eligible:
            reason = f"未进入当日经理池 Top{size}，按画像分流至 {channel}；{score_reason}"
        else:
            reason = f"未达到经理池资格，按画像分流至 {channel}；{score_reason}"
        decisions[customer_id] = ChannelDecision(
            customer_id=customer_id,
            assigned_channel=channel,
            manager_eligible=eligible,
            manager_pool_member=pool_member,
            manager_priority_score=score,
            manager_priority_rank=rank,
            reason=reason,
        )
    return decisions


__all__ = [
    "allocate_manager_customers",
    "build_channel_decisions",
    "manager_priority",
    "resolve_manager_pool_size",
    "select_business_channel",
]
