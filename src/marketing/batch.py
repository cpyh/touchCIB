"""A1客户×产品×可执行渠道排序 + A2硬规则过滤的营销日批。

处理顺序固定为：
1. 规则生成客户可执行渠道集；
2. A1对客户的30个产品×可执行渠道打分，每产品保留最优渠道；
3. A2只做风险最多上浮一档、产品状态、客户状态和起投能力等硬规则过滤；
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
    Customer,
    CustomerBehavior,
)
from .pipeline import _slot_order
from .rules import build_default_engine, normalize_disabled_constraints
from .templates import build_script
from .warehouse import MarketingWarehouseContext

if TYPE_CHECKING:
    from ..partA1serving.predictor import ResponsePredictor


RULE_VERSION = "a1_product_channel_rank_risk_plus_one_v4"
FEATURE_VERSION_PREFIX = "a1_feature_schema_v"
CHANNEL_TIE_PRIORITY = {"manager": 0, "app_push": 1, "call": 2, "sms": 3}


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
    """兼容旧调用：manager 已无资格或配额限制，始终可执行。"""
    del customer, behavior, manager_enabled
    return "manager"


def eligible_business_channels(
    customer: Customer,
    behavior: CustomerBehavior,
    *,
    manager_enabled: bool = True,
    disabled_constraints: Iterable[str] = (),
) -> tuple[str, ...]:
    """返回 A1 排序使用的可执行渠道；manager 对所有客户开放。

    ``manager_enabled`` 仅为兼容旧调用保留，不再影响结果。
    """
    del manager_enabled
    disabled = normalize_disabled_constraints(disabled_constraints)
    channels = ["sms"]
    if (
        "channel_call_complaint_block" in disabled
        or behavior.complaint_count_90d < 2
    ):
        channels.append("call")
    if "channel_app_requires_app" in disabled or customer.has_app:
        channels.append("app_push")
    channels.append("manager")
    return tuple(channels)


def allocate_manager_customers(
    customers: Iterable[Customer],
    *,
    manager_quota: int,
    strategies_per_customer: int = 3,
) -> set[str]:
    """兼容旧调用：manager 不再分配配额，直接向所有客户开放。"""
    del manager_quota
    if strategies_per_customer <= 0:
        raise ValueError("strategies_per_customer must be positive")
    return {customer.customer_id for customer in customers}


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
    disabled_constraints: Iterable[str] = (),
) -> MarketingBatchResult:
    """纯计算阶段；只有全部客户成功后，调用方才进入ADS事务写入。"""
    del manager_quota  # 兼容旧接口；manager 已不限资格和配额。
    disabled = normalize_disabled_constraints(disabled_constraints)
    engine = build_default_engine()
    model_version, feature_version = _model_versions(predictor)
    score_rows: list[tuple[Any, ...]] = []
    decision_rows: list[tuple[Any, ...]] = []
    strategy_rows: list[tuple[Any, ...]] = []
    customer_ids = sorted(context.customers)
    channels_by_customer = {
        customer_id: eligible_business_channels(
            context.customers[customer_id],
            context.behaviors[customer_id],
            disabled_constraints=disabled,
        )
        for customer_id in customer_ids
    }
    product_scores_by_customer: dict[str, dict[str, tuple[float, str]]] = {}
    # 200客户为一块；在块内展开产品×可执行渠道，向量化推理。
    for start in range(0, len(customer_ids), 200):
        customer_chunk = customer_ids[start : start + 200]
        requests = [
            PredictRequest(
                customer_id=customer_id,
                product_id=product.product_id,
                channel=channel,
                contact_date=context.strategy_date.isoformat(),
            )
            for customer_id in customer_chunk
            for product in context.products
            for channel in channels_by_customer[customer_id]
        ]
        predictions = predictor.predict_batch(requests, explain=False)
        if len(predictions) != len(requests):
            raise RuntimeError(
                "A1 batch result count does not match product-channel requests"
            )
        for request, prediction in zip(requests, predictions, strict=True):
            probability = float(prediction.probability)
            product_scores = product_scores_by_customer.setdefault(
                str(request.customer_id), {}
            )
            current = product_scores.get(request.product_id)
            candidate = (probability, request.channel)
            if current is None or (
                candidate[0] > current[0]
                or (
                    candidate[0] == current[0]
                    and CHANNEL_TIE_PRIORITY[candidate[1]]
                    < CHANNEL_TIE_PRIORITY[current[1]]
                )
            ):
                product_scores[request.product_id] = candidate

    for customer_id in customer_ids:
        customer = context.customers[customer_id]
        behavior = context.behaviors[customer_id]
        # 高分参考口径：所有客户都允许产品风险等级最多上浮一档，
        # 上浮产品与偏好内产品一起按 A1 概率竞争 Top3。
        base_risk = int(customer.risk_appetite[1:])
        max_allowed_risk = min(5, base_risk + 1)
        product_channel_scores = product_scores_by_customer[customer_id]
        probability_by_product = {
            product_id: score[0]
            for product_id, score in product_channel_scores.items()
        }
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

        compliant_candidates: list[tuple] = []
        candidate_trace: dict[str, list] = {}
        for product in ordered_products:
            probability = probability_by_product[product.product_id]
            channel = product_channel_scores[product.product_id][1]
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
                "disabled_constraints": disabled,
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
                compliant_candidates.append((product, probability, rank))

        passed_candidates = compliant_candidates[:3]
        if len(passed_candidates) < 3:
            raise RuntimeError(
                f"{customer_id}: A2基础规则过滤后仅剩 {len(passed_candidates)} 个候选"
            )

        for strategy_rank, (product, probability, rank) in enumerate(
            passed_candidates[:3], start=1
        ):
            channel = product_channel_scores[product.product_id][1]
            overshoot = int(product.risk_level[1:]) > base_risk
            recommended_time = _slot_order(customer, channel)[strategy_rank - 1]
            marketing_script = build_script(
                customer,
                product,
                channel,
                overshoot=overshoot,
            )
            execution_context = {
                "customer": customer,
                "behavior": behavior,
                "product": product,
                "strategy_date": context.strategy_date,
                "max_allowed_risk": max_allowed_risk,
                "invest_budget": customer.aum,
                "channel": channel,
                "disabled_constraints": disabled,
                "recommended_time": recommended_time,
                "marketing_script": marketing_script,
                "overshoot": overshoot,
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
                    "（产品风险等级按规则上浮一档）"
                    if overshoot
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
    "eligible_business_channels",
    "persist_marketing_batch",
    "select_business_channel",
]
