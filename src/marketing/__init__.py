"""营销策略规则/流程引擎（A2，设计定稿 v2，见 docs/sdd-marketing.md）。"""

from .engine import Rule, RuleEngine
from .models import (
    CHANNELS,
    DEFAULT_MANAGER_DAILY_CAPACITY,
    DEFAULT_MANAGER_POOL_SIZE,
    DEFAULT_MANAGER_QUOTA,
    DEFAULT_TOP_N,
    RISK_RANK,
    STRATEGY_COLUMNS,
    TIME_SLOTS,
    Customer,
    CustomerBehavior,
    ChannelDecision,
    Product,
    RuleOutcome,
    StepRecord,
    StrategyItem,
    StrategyRequest,
    StrategyResult,
)
from .pipeline import generate_strategies
from .rules import RULES, build_default_engine
from .templates import (
    COMPLIANCE_NOTE,
    OVERSHOOT_NOTE,
    build_script,
)
from .validate import validate_strategy_file, validate_strategy_rows

__all__ = [
    "CHANNELS",
    "COMPLIANCE_NOTE",
    "DEFAULT_MANAGER_QUOTA",
    "DEFAULT_MANAGER_POOL_SIZE",
    "DEFAULT_MANAGER_DAILY_CAPACITY",
    "DEFAULT_TOP_N",
    "OVERSHOOT_NOTE",
    "RISK_RANK",
    "RULES",
    "STRATEGY_COLUMNS",
    "TIME_SLOTS",
    "Customer",
    "CustomerBehavior",
    "ChannelDecision",
    "Product",
    "Rule",
    "RuleEngine",
    "RuleOutcome",
    "StepRecord",
    "StrategyItem",
    "StrategyRequest",
    "StrategyResult",
    "build_default_engine",
    "build_script",
    "generate_strategies",
    "validate_strategy_file",
    "validate_strategy_rows",
]
