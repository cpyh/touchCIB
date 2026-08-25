"""A2 两阶段策略生成流水线（设计定稿 v2，详见 docs/sdd-marketing.md）。

阶段一（全局批次）：
    产品排序 = A1 模型概率 + w_cf × 持有产品协同过滤相似度（模型管产品）；
    合规顺位过滤（风险偏好内优先，不足 3 个时自动溢出 1 级）；
    manager 渠道配额分配（资格 + 全局配额，按客户价值排序）。
阶段二（逐客户）：
    渠道（rank 顺位取不同渠道）→ 时段（职业×渠道偏好序）→ 话术 → 规则回验。

全部确定性执行（排序 tie-break 用 product_id / customer_id），无需随机数。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from .collaborative import build_co_holding_similarity, customer_cf_scores
from .engine import RuleEngine
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
    RISK_RANK,
    STRATEGY_COLUMNS,
    TIME_SLOTS,
    Product,
    StepRecord,
    StrategyItem,
    StrategyRequest,
    StrategyResult,
)
from .rules import RULES, build_default_engine
from .templates import build_script
from .validate import validate_strategy_file

PROJECT_DIR = Path(__file__).resolve().parents[2]

VIP_RANK = {"钻石": 3, "金卡": 2, "银卡": 1, "普通": 0}

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


def _rank_score(
    customer_id: str,
    product: Product,
    model_scores: Mapping[tuple[str, str], float],
    cf_scores: Mapping[tuple[str, str], float],
    w_cf: float,
) -> tuple[float, float, float]:
    model_prob = float(model_scores.get((customer_id, product.product_id), 0.0))
    if not 0.0 <= model_prob <= 1.0:
        raise ValueError(
            f"model score out of [0,1] for {customer_id}/{product.product_id}"
        )
    cf_score = float(cf_scores.get((customer_id, product.product_id), 0.0))
    return model_prob + w_cf * cf_score, model_prob, cf_score


def _compliance_evaluate(
    engine: RuleEngine,
    customer_id: str,
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
    cf_scores: Mapping[tuple[str, str], float],
    w_cf: float,
) -> list[tuple[Product, float, float, float, bool]]:
    def score_sort(pool: Sequence[Product]) -> list[tuple[Product, float, float, float]]:
        scored = [
            (p, *_rank_score(customer_id, p, model_scores, cf_scores, w_cf))
            for p in pool
        ]
        scored.sort(key=lambda entry: (-entry[1], entry[0].product_id))
        return scored

    selected: list[tuple[Product, float, float, float, bool]] = [
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
    ladder: list[str] = []
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
# manager 配额分配（阶段一全局步骤）
# ----------------------------------------------------------------


def _allocate_manager(
    requests: Sequence[StrategyRequest], quota: int
) -> dict[str, tuple[int, ...]]:
    """按客户价值分配 manager 渠道名额，返回 customer_id -> 命中 rank 列表。"""
    eligible = [
        request
        for request in requests
        if (
            request.customer.vip_level in MANAGER_ELIGIBLE_VIP
            or request.customer.aum >= MANAGER_ELIGIBLE_AUM
        )
    ]
    eligible.sort(
        key=lambda request: (
            -VIP_RANK.get(request.customer.vip_level, 0),
            -request.customer.aum,
            request.customer.customer_id,
        )
    )
    plan: dict[str, list[int]] = {}
    used = 0
    # 第一轮：每人至多 1 条（rank 1）
    for request in eligible:
        if used >= quota:
            break
        if 1 <= request.top_n:
            plan.setdefault(request.customer.customer_id, []).append(1)
            used += 1
    # 第二轮：配额有余量时，钻石/金卡可拿第 2 条（rank 2）
    if used < quota:
        for request in eligible:
            if used >= quota:
                break
            ranks = plan.get(request.customer.customer_id, [])
            if (
                request.customer.vip_level in MANAGER_ELIGIBLE_VIP
                and len(ranks) < 2
                and 2 <= request.top_n
            ):
                ranks.append(2)
                used += 1
    return {
        customer_id: tuple(sorted(ranks))
        for customer_id, ranks in plan.items()
        if ranks
    }


# ----------------------------------------------------------------
# 阶段二：单客户生成
# ----------------------------------------------------------------


def _plan_customer(
    request: StrategyRequest,
    products: Sequence[Product],
    engine: RuleEngine,
    manager_ranks: Sequence[int],
    model_scores: Mapping[tuple[str, str], float],
    cf_scores: Mapping[tuple[str, str], float],
    w_cf: float,
) -> StrategyResult:
    customer = request.customer
    behavior = request.effective_behavior()
    base_rank = RISK_RANK[customer.risk_appetite]
    steps: list[StepRecord] = []

    # ---- Step 2 合规过滤（先合规池，不足时溢出 1 级） ----
    compliant, blocked_details = _compliance_evaluate(
        engine, customer.customer_id, request.strategy_date, products,
        max_allowed_risk=base_rank, customer=customer,
    )
    overshoot_pool: list[Product] = []
    overshoot = 0
    if len(compliant) < request.top_n:
        overshoot = 1
        overshoot_pool, overflow_blocked = _compliance_evaluate(
            engine, customer.customer_id, request.strategy_date, products,
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
        model_scores, cf_scores, w_cf,
    )
    steps.append(
        StepRecord(
            "ranking",
            f"Top{len(selected)} 排序完成（A1 概率 + {w_cf}×协同过滤相似度）",
            tuple(
                f"{p.product_id}: score={score:.6f} "
                f"(model={model_prob:.4f}, cf={cf_score:.4f})"
                for p, score, model_prob, cf_score, _ in selected
            ),
        )
    )

    # ---- Step 5/6/7 渠道 → 时段 → 话术 ----
    ladder = _channel_ladder(customer, behavior)
    items: list[StrategyItem] = []
    channel_details: list[str] = []
    slot_details: list[str] = []
    non_manager_pos = 0
    for position, (product, score, model_prob, cf_score, is_overshoot) in enumerate(
        selected, start=1
    ):
        rank = position
        if rank in manager_ranks:
            channel = "manager"
            channel_details.append(
                f"rank{rank}: manager（配额命中，VIP={customer.vip_level}，"
                f"AUM={customer.aum:.0f}）"
            )
        else:
            channel = ladder[non_manager_pos % len(ladder)]
            non_manager_pos += 1
            reason = {
                "app_push": "已安装 App",
                "call": "无投诉记录",
                "sms": "短信兜底",
            }.get(channel, channel)
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
            "manager_allowed": rank in manager_ranks,
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
                score=score,
                model_prob=model_prob,
                cf_score=cf_score,
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
    cf_scores: Mapping[tuple[str, str], float] | None = None,
    w_cf: float = DEFAULT_W_CF,
    manager_quota: int = DEFAULT_MANAGER_QUOTA,
    engine: RuleEngine | None = None,
) -> list[StrategyResult]:
    """批量生成全部客户的 Top N 策略（两阶段，含 manager 全局配额）。"""
    if not requests or not products:
        raise ValueError("requests and products must not be empty")
    product_ids = [p.product_id for p in products]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("duplicate product_id in product pool")
    if manager_quota < 0:
        raise ValueError("manager_quota must be non-negative")

    engine = engine or build_default_engine()
    model_scores = model_scores or {}
    cf_scores = cf_scores or {}
    manager_plan = _allocate_manager(requests, manager_quota)

    results: list[StrategyResult] = []
    for request in requests:
        results.append(
            _plan_customer(
                request,
                products,
                engine,
                manager_plan.get(request.customer.customer_id, ()),
                model_scores,
                cf_scores,
                w_cf,
            )
        )
    return results


# ----------------------------------------------------------------
# 命令行入口
# ----------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A2 营销策略生成（规则/流程引擎）")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR / "src" / "data" / "raw")
    parser.add_argument(
        "--test-contacts",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "raw" / "partA_test_contacts.csv",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=PROJECT_DIR / "partA_prediction.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "partA_strategy.csv",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "outputs" / "a2_strategy_audit.csv",
    )
    parser.add_argument(
        "--cf-audit",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "outputs" / "a2_cf_similarity.csv",
    )
    parser.add_argument("--manager-quota", type=int, default=DEFAULT_MANAGER_QUOTA)
    parser.add_argument("--w-cf", type=float, default=DEFAULT_W_CF)
    return parser.parse_args(argv)


def write_strategy_csv(output_path: Path, results: Sequence[StrategyResult]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=STRATEGY_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerows(result.to_rows())


def write_strategy_audit(output_path: Path, results: Sequence[StrategyResult]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "customer_id", "rank", "product_id", "score", "model_prob",
                "cf_score", "overshoot", "recommended_channel",
                "recommended_time", "script_length",
            ]
        )
        for result in results:
            for item in result.items:
                writer.writerow(
                    [
                        result.customer_id, item.rank, item.product_id,
                        f"{item.score:.8f}", f"{item.model_prob:.8f}",
                        f"{item.cf_score:.8f}", int(item.overshoot),
                        item.recommended_channel, item.recommended_time,
                        len(item.marketing_script),
                    ]
                )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    customers = load_customers(args.data_dir / "t_customer.csv")
    products = load_products(args.data_dir / "t_product.csv")
    strategy_dates = load_strategy_customers(
        args.data_dir / "partA_strategy_customers.csv"
    )

    import pandas as pd

    events = pd.read_csv(
        args.data_dir / "t_event.csv", dtype={"customer_id": str}
    )
    holdings = pd.read_csv(
        args.data_dir / "t_holding.csv",
        dtype={"customer_id": str, "product_id": str},
    )
    behaviors = build_behaviors(
        customers, events, holdings, strategy_dates
    )
    model_scores = load_model_scores(args.test_contacts, args.predictions)

    similarity = build_co_holding_similarity(
        holdings, as_of=max(strategy_dates.values())
    )
    cf_scores = customer_cf_scores(
        similarity,
        {
            cid: behavior.holding_product_ids
            for cid, behavior in behaviors.items()
        },
        [p.product_id for p in products],
    )
    similarity.to_csv(args.cf_audit, index=False)

    requests = [
        StrategyRequest(
            customer=customers[customer_id],
            strategy_date=strategy_date,
            behavior=behaviors[customer_id],
            top_n=DEFAULT_TOP_N,
        )
        for customer_id, strategy_date in strategy_dates.items()
    ]

    results = generate_strategies(
        requests,
        products,
        model_scores=model_scores,
        cf_scores=cf_scores,
        w_cf=args.w_cf,
        manager_quota=args.manager_quota,
    )

    write_strategy_csv(args.output, results)
    write_strategy_audit(args.audit_output, results)
    errors = validate_strategy_file(
        args.output, expected_customers=set(strategy_dates)
    )

    manager_rows = sum(
        1
        for result in results
        for item in result.items
        if item.recommended_channel == "manager"
    )
    overshoot_rows = sum(
        1 for result in results for item in result.items if item.overshoot
    )
    total_rows = sum(len(result.items) for result in results)

    print(f"customers={len(results)} rows={total_rows}")
    print(f"manager_rows={manager_rows} overshoot_rows={overshoot_rows}")
    print(f"validation_errors={len(errors)}")
    if errors:
        for error in errors[:10]:
            print(f"  - {error}")
    print(f"strategy={args.output}")
    print(f"audit={args.audit_output}")
    print(f"cf_similarity={args.cf_audit}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
