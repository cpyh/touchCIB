"""响应归因：窗口 + 匹配 + 边界规则（设计见 docs/demo-design.md §3）。

口径与题目 A2 判分同构：
    "下一周期实际购买产品 ∈ 客户 Top3 → 该客户命中"

- 窗口：strategy_date ≤ buy_date ≤ strategy_date + window_days（默认 30，参数可调）
- 匹配：购买产品 ∈ 客户 Top3 → 归因到对应 rank 的策略（strategy_id = {customer_id}:{rank}）
- 边界：策略前购买不归因；窗口外不归因；非 Top3 不归因；重复购买只记首次（由写入方校验）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class AttributionOutcome:
    """一次购买事实的归因结果。"""

    matched: bool
    strategy_id: str | None
    reason: str
    rank: int | None = None


def attribute_purchase(
    *,
    customer_id: str,
    product_id: str,
    buy_date: date,
    strategy_date: date,
    top3: dict[str, tuple[str, str, str]],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> AttributionOutcome:
    """对一条购买事实执行归因规则，返回命中策略或拒绝原因。"""
    if not 1 <= window_days <= 365:
        raise ValueError("window_days must be between 1 and 365")

    products = top3.get(customer_id)
    if not products:
        return AttributionOutcome(
            False,
            None,
            f"客户 {customer_id} 不在目标名单或没有 Top3 策略",
        )

    if buy_date < strategy_date:
        return AttributionOutcome(
            False,
            None,
            f"购买日期 {buy_date} 早于策略日期 {strategy_date}（触达前购买，不归因）",
        )

    window_end = strategy_date + timedelta(days=window_days)
    if buy_date > window_end:
        return AttributionOutcome(
            False,
            None,
            f"购买日期 {buy_date} 超出归因窗口（{strategy_date} +{window_days} 天"
            f"= {window_end}），不归因",
        )

    try:
        rank = products.index(product_id) + 1
    except ValueError:
        return AttributionOutcome(
            False,
            None,
            f"产品 {product_id} 不在客户 {customer_id} 的 Top3 内，"
            "不归因（与题目 HitRate 口径一致）",
        )

    return AttributionOutcome(
        True,
        f"{customer_id}:{rank}",
        f"命中 Top3 第 {rank} 位，窗口内购买，归因成功",
        rank,
    )


def find_responses(
    purchases: Sequence[tuple[str, str, date]],
    *,
    strategy_date: date,
    top3: dict[str, tuple[str, str, str]],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[AttributionOutcome]:
    """批量归因（T+1 扫描与演示预置数据生成用）。

    purchases: (customer_id, product_id, buy_date) 三元组列表。
    返回每个购买事实的归因结果（未命中的也在内，供审计）。
    """
    return [
        attribute_purchase(
            customer_id=customer_id,
            product_id=product_id,
            buy_date=buy_date,
            strategy_date=strategy_date,
            top3=top3,
            window_days=window_days,
        )
        for customer_id, product_id, buy_date in purchases
    ]
