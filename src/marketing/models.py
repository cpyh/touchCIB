"""A2 契约常量与数据结构（团队对齐基线，见 docs/sdd-marketing.md）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

# ----------------------------------------------------------------
# 提交契约常量（与题目原文完全一致）
# ----------------------------------------------------------------

CHANNELS = ("sms", "call", "app_push", "manager")

TIME_SLOTS = (
    "工作日09:00-12:00",
    "工作日12:00-14:00",
    "工作日18:00-21:00",
    "周末09:00-12:00",
    "周末14:00-18:00",
)

STRATEGY_COLUMNS = (
    "customer_id",
    "rank",
    "product_id",
    "recommended_channel",
    "recommended_time",
    "marketing_script",
)

RISK_RANK = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}

# 经理渠道采用“每日动态候选池 + 当日处理容量”，不维护跨日静态池状态。
MANAGER_ELIGIBLE_VIP = ("金卡", "钻石")
MANAGER_ELIGIBLE_AUM = 500_000.0
# 旧配额按策略行计数（600=200位客户×3条策略），仅保留接口兼容。
DEFAULT_MANAGER_QUOTA = 600
DEFAULT_MANAGER_POOL_SIZE = 200
DEFAULT_MANAGER_DAILY_CAPACITY = 12
DEFAULT_TOP_N = 3

# 风险溢出上限（所有候选统一允许上浮的最大等级数）
MAX_RISK_OVERSHOOT = 1


# ----------------------------------------------------------------
# 业务实体
# ----------------------------------------------------------------


@dataclass(frozen=True)
class Customer:
    customer_id: str
    age_group: str
    city: str
    occupation: str
    income_level: str
    register_date: date
    aum: float
    risk_appetite: str
    vip_level: str
    has_app: bool

    def __post_init__(self) -> None:
        if self.risk_appetite not in RISK_RANK:
            raise ValueError(f"unknown risk_appetite: {self.risk_appetite}")


@dataclass(frozen=True)
class Product:
    product_id: str
    product_name: str
    product_type: str
    risk_level: str
    expected_return: float
    volatility: float
    min_invest: float
    duration_days: int
    liquidity: str
    launch_date: date

    def __post_init__(self) -> None:
        if self.risk_level not in RISK_RANK:
            raise ValueError(f"unknown risk_level: {self.risk_level}")


@dataclass(frozen=True)
class CustomerBehavior:
    """持仓与行为事件聚合（必须按 strategy_date 做 as-of 截断后传入）。"""

    customer_id: str
    holding_product_ids: tuple[str, ...] = ()
    complaint_count_90d: int = 0
    consult_count_90d: int = 0
    login_count_30d: int = 0


@dataclass(frozen=True)
class ChannelDecision:
    """单客户当日执行渠道决策；由日批画像计算并固化为当日快照。"""

    customer_id: str
    assigned_channel: str
    manager_eligible: bool
    manager_pool_member: bool
    manager_priority_score: float
    manager_priority_rank: int | None
    reason: str


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class StepRecord:
    """流水线单步轨迹，供看板与答辩展示。"""

    step: str
    summary: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyItem:
    """单条营销策略（partA_strategy.csv 的一行）。"""

    rank: int
    product_id: str
    recommended_channel: str
    recommended_time: str
    marketing_script: str
    model_prob: float
    overshoot: bool
    rule_trace: tuple[RuleOutcome, ...] = ()

    def to_row(self, customer_id: str) -> dict[str, str]:
        return {
            "customer_id": customer_id,
            "rank": str(self.rank),
            "product_id": self.product_id,
            "recommended_channel": self.recommended_channel,
            "recommended_time": self.recommended_time,
            "marketing_script": self.marketing_script,
        }


@dataclass(frozen=True)
class StrategyResult:
    """单客户 Top N 策略生成结果。"""

    customer_id: str
    strategy_date: date
    items: tuple[StrategyItem, ...]
    steps: tuple[StepRecord, ...]

    def to_rows(self) -> list[dict[str, str]]:
        return [item.to_row(self.customer_id) for item in self.items]

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "strategy_date": self.strategy_date.isoformat(),
            "steps": [
                {"step": s.step, "summary": s.summary, "details": list(s.details)}
                for s in self.steps
            ],
            "items": [
                {
                    **item.to_row(self.customer_id),
                    "model_prob": item.model_prob,
                    "overshoot": item.overshoot,
                    "rule_trace": [
                        {"rule_id": o.rule_id, "passed": o.passed, "reason": o.reason}
                        for o in item.rule_trace
                    ],
                }
                for item in self.items
            ],
        }


@dataclass(frozen=True)
class StrategyRequest:
    """单客户策略生成请求（产品排序信号由批次入口统一注入）。"""

    customer: Customer
    strategy_date: date
    behavior: CustomerBehavior | None = None
    top_n: int = DEFAULT_TOP_N

    def __post_init__(self) -> None:
        if not 1 <= self.top_n <= 30:
            raise ValueError("top_n must be between 1 and 30")

    def effective_behavior(self) -> CustomerBehavior:
        return self.behavior or CustomerBehavior(
            customer_id=self.customer.customer_id
        )
