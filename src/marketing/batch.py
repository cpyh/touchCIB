"""A1排序 + A2基础规则过滤的幂等营销日批。

处理顺序固定为：
1. 规则选择客户可执行渠道；
2. A1对客户的30个产品打分并排序；
3. A2只做适当性、产品状态、客户状态和起投能力等硬规则过滤；
4. 从通过候选中取Top3，生成时段、话术与完整规则轨迹；
5. 同一事务替换本批客户在三张ADS表中的结果。

本模块只读取 MySQL DWD，也不读取任何提交 CSV。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Callable, Iterable

from ..database import database_connection
from ..partA1serving.feature_service import PredictRequest
from .models import (
    DEFAULT_MANAGER_QUOTA,
    MANAGER_ELIGIBLE_AUM,
    MANAGER_ELIGIBLE_VIP,
    Customer,
    CustomerBehavior,
)
from .pipeline import _slot_order
from .rules import build_default_engine
from .templates import build_script
from .warehouse import MarketingWarehouseContext

if TYPE_CHECKING:
    from ..partA1serving.predictor import ResponsePredictor


RULE_VERSION = "a1_rank_basic_rules_v1"
FEATURE_VERSION_PREFIX = "a1_feature_schema_v"
VIP_PRIORITY = {"钻石": 3, "金卡": 2, "银卡": 1, "普通": 0}


@dataclass(frozen=True)
class MarketingBatchResult:
    strategy_date: date
    batch_id: str
    model_version: str
    feature_version: str
    customer_ids: tuple[str, ...]
    score_rows: tuple[tuple[Any, ...], ...]
    decision_rows: tuple[tuple[Any, ...], ...]
    strategy_rows: tuple[tuple[Any, ...], ...]

    @property
    def customer_count(self) -> int:
        return len(self.customer_ids)


def select_business_channel(
    customer: Customer,
    behavior: CustomerBehavior,
    *,
    manager_enabled: bool = True,
) -> str:
    """用可审计规则选择A1评分渠道，避免模型对不可执行渠道打高分。"""
    if manager_enabled and (
        customer.vip_level in MANAGER_ELIGIBLE_VIP
        or customer.aum >= MANAGER_ELIGIBLE_AUM
    ):
        return "manager"
    if customer.has_app:
        return "app_push"
    if behavior.complaint_count_90d < 2:
        return "call"
    return "sms"


def allocate_manager_customers(
    customers: Iterable[Customer],
    *,
    manager_quota: int,
    strategies_per_customer: int = 3,
) -> set[str]:
    """分配 manager 渠道客户，配额单位为最终策略行数。

    A1 的渠道是模型特征，因此同一客户的 30 产品必须先固定一个可执行渠道。
    为保证评分渠道与最终 Top3 渠道一致，manager 按完整客户 Top3 分配；不足
    一个完整 Top3 的尾数不使用。排序完全确定，便于离线提交与 ADS 日批复现。
    """
    if manager_quota < 0:
        raise ValueError("manager_quota must be non-negative")
    if strategies_per_customer <= 0:
        raise ValueError("strategies_per_customer must be positive")
    capacity = manager_quota // strategies_per_customer
    eligible = [
        customer
        for customer in customers
        if customer.vip_level in MANAGER_ELIGIBLE_VIP
        or customer.aum >= MANAGER_ELIGIBLE_AUM
    ]
    eligible.sort(
        key=lambda customer: (
            -VIP_PRIORITY.get(customer.vip_level, 0),
            -customer.aum,
            customer.customer_id,
        )
    )
    return {customer.customer_id for customer in eligible[:capacity]}


def _trace_json(outcomes) -> str:
    return json.dumps(
        [
            {
                "rule_id": outcome.rule_id,
                "passed": outcome.passed,
                "reason": outcome.reason,
            }
            for outcome in outcomes
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _model_versions(predictor: "ResponsePredictor") -> tuple[str, str]:
    meta = predictor.meta
    model_version = (
        f"{getattr(meta, 'profile', predictor.profile)}:"
        f"{getattr(meta, 'model_name', predictor.model_name)}:"
        f"{str(getattr(meta, 'trained_at', 'unknown'))[:10]}"
    )
    feature_version = f"{FEATURE_VERSION_PREFIX}{getattr(meta, 'schema_version', 1)}"
    return model_version, feature_version


def compute_marketing_batch(
    context: MarketingWarehouseContext,
    predictor: "ResponsePredictor",
    *,
    batch_id: str,
    manager_quota: int = DEFAULT_MANAGER_QUOTA,
) -> MarketingBatchResult:
    """纯计算阶段；只有全部客户成功后，调用方才进入ADS事务写入。"""
    engine = build_default_engine()
    model_version, feature_version = _model_versions(predictor)
    score_rows: list[tuple[Any, ...]] = []
    decision_rows: list[tuple[Any, ...]] = []
    strategy_rows: list[tuple[Any, ...]] = []
    customer_ids = sorted(context.customers)
    manager_customers = allocate_manager_customers(
        context.customers.values(),
        manager_quota=manager_quota,
    )
    channel_by_customer = {
        customer_id: select_business_channel(
            context.customers[customer_id],
            context.behaviors[customer_id],
            manager_enabled=customer_id in manager_customers,
        )
        for customer_id in customer_ids
    }
    probability_by_customer: dict[str, dict[str, float]] = {}
    # 200客户×30产品为一块：拼表和模型均向量化，同时控制内存。
    for start in range(0, len(customer_ids), 200):
        customer_chunk = customer_ids[start : start + 200]
        requests = [
            PredictRequest(
                customer_id=customer_id,
                product_id=product.product_id,
                channel=channel_by_customer[customer_id],
                contact_date=context.strategy_date.isoformat(),
            )
            for customer_id in customer_chunk
            for product in context.products
        ]
        predictions = predictor.predict_batch(requests, explain=False)
        for prediction in predictions:
            probability_by_customer.setdefault(
                prediction.customer_id, {}
            )[prediction.product_id] = float(prediction.probability)

    for customer_id in customer_ids:
        customer = context.customers[customer_id]
        behavior = context.behaviors[customer_id]
        # 优先严格按客户风险偏好筛选；只有严格候选不足3个时，才允许
        # 上浮一档。放宽结果会在risk_match轨迹中明确标记。
        base_risk = int(customer.risk_appetite[1:])
        strict_candidate_count = sum(
            int(product.risk_level[1:]) <= base_risk
            and product.launch_date <= context.strategy_date
            and customer.aum >= product.min_invest
            for product in context.products
        )
        max_allowed_risk = (
            base_risk if strict_candidate_count >= 3 else min(5, base_risk + 1)
        )
        channel = channel_by_customer[customer_id]
        probability_by_product = probability_by_customer[customer_id]
        ordered_products = sorted(
            context.products,
            key=lambda product: (
                -probability_by_product[product.product_id],
                product.product_id,
            ),
        )
        a1_rank = {
            product.product_id: index
            for index, product in enumerate(ordered_products, start=1)
        }

        strict_candidates: list[tuple] = []
        overshoot_candidates: list[tuple] = []
        candidate_trace: dict[str, list] = {}
        for product in ordered_products:
            probability = probability_by_product[product.product_id]
            rank = a1_rank[product.product_id]
            score_rows.append(
                (
                    context.strategy_date,
                    customer_id,
                    product.product_id,
                    channel,
                    probability,
                    rank,
                    model_version,
                    feature_version,
                    context.strategy_date,
                    batch_id,
                )
            )
            compliance_context = {
                "customer": customer,
                "behavior": behavior,
                "product": product,
                "strategy_date": context.strategy_date,
                "max_allowed_risk": max_allowed_risk,
                "invest_budget": customer.aum,
            }
            outcomes = engine.evaluate_all(
                compliance_context,
                categories=("compliance", "batch_compliance"),
            )
            failures = [outcome.reason for outcome in outcomes if not outcome.passed]
            passed = not failures
            candidate_trace[product.product_id] = outcomes
            decision_rows.append(
                (
                    context.strategy_date,
                    customer_id,
                    product.product_id,
                    rank,
                    probability,
                    channel,
                    int(passed),
                    _trace_json(outcomes),
                    "; ".join(failures)[:512] or None,
                    batch_id,
                )
            )
            if passed:
                target = (
                    strict_candidates
                    if int(product.risk_level[1:]) <= base_risk
                    else overshoot_candidates
                )
                target.append((product, probability, rank))

        passed_candidates = [
            *strict_candidates[:3],
            *overshoot_candidates[: max(0, 3 - len(strict_candidates))],
        ]
        if len(passed_candidates) < 3:
            raise RuntimeError(
                f"{customer_id}: A2基础规则过滤后仅剩 {len(passed_candidates)} 个候选"
            )

        for strategy_rank, (product, probability, rank) in enumerate(
            passed_candidates[:3], start=1
        ):
            recommended_time = _slot_order(customer, channel)[strategy_rank - 1]
            marketing_script = build_script(
                customer,
                product,
                channel,
                overshoot=False,
            )
            execution_context = {
                "customer": customer,
                "behavior": behavior,
                "product": product,
                "strategy_date": context.strategy_date,
                "max_allowed_risk": max_allowed_risk,
                "invest_budget": customer.aum,
                "channel": channel,
                "manager_allowed": channel == "manager",
                "recommended_time": recommended_time,
                "marketing_script": marketing_script,
                "overshoot": False,
            }
            extra_outcomes = engine.evaluate_all(
                execution_context,
                categories=("record", "channel", "timing", "script"),
            )
            all_outcomes = [*candidate_trace[product.product_id], *extra_outcomes]
            failures = [outcome.reason for outcome in all_outcomes if not outcome.passed]
            if failures:
                raise RuntimeError(
                    f"{customer_id}/{product.product_id}: 执行规则失败："
                    + "; ".join(failures)
                )
            selection_reason = (
                f"A1原始排名第{rank}（概率{probability:.2%}），"
                f"通过{len(all_outcomes)}项规则，进入过滤后Top3第{strategy_rank}位"
                + (
                    "（严格风险候选不足3个，按规则放宽一档补位）"
                    if int(product.risk_level[1:]) > base_risk
                    else ""
                )
            )
            strategy_rows.append(
                (
                    context.strategy_date,
                    customer_id,
                    strategy_rank,
                    f"{customer_id}:{strategy_rank}",
                    product.product_id,
                    channel,
                    recommended_time,
                    marketing_script,
                    probability,
                    rank,
                    _trace_json(all_outcomes),
                    selection_reason,
                    model_version,
                    RULE_VERSION,
                    batch_id,
                )
            )

    return MarketingBatchResult(
        strategy_date=context.strategy_date,
        batch_id=batch_id,
        model_version=model_version,
        feature_version=feature_version,
        customer_ids=tuple(sorted(context.customers)),
        score_rows=tuple(score_rows),
        decision_rows=tuple(decision_rows),
        strategy_rows=tuple(strategy_rows),
    )


def _chunks(values: tuple[tuple[Any, ...], ...], size: int = 2_000):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def persist_marketing_batch(
    result: MarketingBatchResult,
    *,
    connection_factory: Callable = database_connection,
) -> None:
    """在单事务中替换同日同客户结果；重复执行不会产生重复数据。"""
    if not result.customer_ids:
        return
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            for customer_chunk in (
                result.customer_ids[start : start + 500]
                for start in range(0, len(result.customer_ids), 500)
            ):
                placeholders = ",".join(["%s"] * len(customer_chunk))
                params = (result.strategy_date, *customer_chunk)
                for table in (
                    "ads_marketing_strategy",
                    "ads_a2_candidate_decision",
                    "ads_a1_customer_product_score",
                ):
                    cursor.execute(
                        f"DELETE FROM {table} WHERE strategy_date=%s "
                        f"AND customer_id IN ({placeholders})",
                        params,
                    )

            score_sql = (
                "INSERT INTO ads_a1_customer_product_score "
                "(strategy_date, customer_id, product_id, recommended_channel, "
                "response_prob, a1_rank, model_version, feature_version, "
                "feature_as_of_date, batch_id) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            decision_sql = (
                "INSERT INTO ads_a2_candidate_decision "
                "(strategy_date, customer_id, product_id, a1_rank, response_prob, "
                "recommended_channel, rule_passed, rule_trace_json, filter_reason, "
                "batch_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            strategy_sql = (
                "INSERT INTO ads_marketing_strategy "
                "(strategy_date, customer_id, strategy_rank, strategy_id, product_id, "
                "recommended_channel, recommended_time, marketing_script, "
                "a1_probability, a1_rank, rule_trace_json, selection_reason, "
                "model_version, rule_version, batch_id) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            for chunk in _chunks(result.score_rows):
                cursor.executemany(score_sql, chunk)
            for chunk in _chunks(result.decision_rows):
                cursor.executemany(decision_sql, chunk)
            for chunk in _chunks(result.strategy_rows):
                cursor.executemany(strategy_sql, chunk)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "MarketingBatchResult",
    "RULE_VERSION",
    "allocate_manager_customers",
    "compute_marketing_batch",
    "persist_marketing_batch",
    "select_business_channel",
]
