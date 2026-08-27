"""A2 规则目录：合规 / 渠道 / 时段 / 话术 四类规则（设计定稿 v2）。

设计要点（详见 docs/sdd-marketing.md）：
- 模型管产品，规则管其余：产品排序只使用 A1 预测概率，
  规则只做合规拦截、渠道/时段/话术决策与格式校验；
- duration_valid 与 min_invest 为"记录型"规则：只留痕、不拦截
  （评分口径不校验存续期/起投额，产品池以发放的 30 个为准）；
- risk_match 支持"溢出 1 级"：所有客户均允许产品风险等级最多上浮一档，
  并与偏好内产品一起按 A1 概率排序；溢出产品的话术强制带风险提示。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Callable

from .models import (
    MAX_RISK_OVERSHOOT,
    RISK_RANK,
    TIME_SLOTS,
    RuleOutcome,
)
from .templates import COMPLIANCE_NOTE, OVERSHOOT_NOTE

RuleContext = dict

TOGGLEABLE_CONSTRAINT_IDS = frozenset(
    {
        "aum_affordability",
        "channel_app_requires_app",
        "channel_call_complaint_block",
    }
)


def normalize_disabled_constraints(
    values: Iterable[str] | None,
) -> frozenset[str]:
    """校验试算可关闭的约束；正式日批默认传空集合。"""
    if values is None:
        return frozenset()
    if isinstance(values, (str, bytes)):
        raise ValueError("disabled_constraints must be an array of rule ids")
    normalized = frozenset(values)
    if any(not isinstance(value, str) for value in normalized):
        raise ValueError("disabled_constraints must contain only rule ids")
    unknown = normalized - TOGGLEABLE_CONSTRAINT_IDS
    if unknown:
        raise ValueError(
            "unsupported disabled constraint: " + ", ".join(sorted(unknown))
        )
    return normalized


def _constraint_disabled(ctx: RuleContext, rule_id: str) -> bool:
    return rule_id in ctx.get("disabled_constraints", ())


# ----------------------------------------------------------------
# 规则定义
# ----------------------------------------------------------------


def _rule(
    rule_id: str,
    name: str,
    category: str,
    description: str,
    check: Callable[[RuleContext], RuleOutcome],
    *,
    hard: bool = True,
) -> dict:
    return {
        "rule_id": rule_id,
        "name": name,
        "category": category,
        "description": description,
        "hard": hard,
        "check": check,
    }


# ---------- 合规类 ----------


def _check_risk_match(ctx: RuleContext) -> RuleOutcome:
    customer = ctx["customer"]
    product = ctx["product"]
    base = RISK_RANK[customer.risk_appetite]
    allowed = ctx.get("max_allowed_risk", base)
    if RISK_RANK[product.risk_level] <= allowed:
        if RISK_RANK[product.risk_level] > base:
            return RuleOutcome(
                "risk_match",
                True,
                f"溢出通过：产品 {product.risk_level} 高于客户偏好 "
                f"{customer.risk_appetite} 一档（允许上浮 {MAX_RISK_OVERSHOOT} 级）",
            )
        return RuleOutcome("risk_match", True, "产品风险等级在客户偏好范围内")
    return RuleOutcome(
        "risk_match",
        False,
        f"产品 {product.risk_level} 超出客户风险偏好 {customer.risk_appetite}"
        f"（允许溢出上限 {MAX_RISK_OVERSHOOT} 级）",
    )


def _check_product_launched(ctx: RuleContext) -> RuleOutcome:
    product = ctx["product"]
    if product.launch_date <= ctx["strategy_date"]:
        return RuleOutcome("product_launched", True, "产品已成立")
    return RuleOutcome(
        "product_launched",
        False,
        f"产品 {product.product_id} 成立日期 {product.launch_date} "
        f"晚于策略日期 {ctx['strategy_date']}",
    )


def _check_customer_registered(ctx: RuleContext) -> RuleOutcome:
    customer = ctx["customer"]
    if customer.register_date <= ctx["strategy_date"]:
        return RuleOutcome("customer_registered", True, "客户已注册")
    return RuleOutcome(
        "customer_registered",
        False,
        f"客户注册日期 {customer.register_date} 晚于策略日期 {ctx['strategy_date']}",
    )


def _check_aum_affordability(ctx: RuleContext) -> RuleOutcome:
    """业务批处理硬规则：客户可投资资产至少覆盖产品起投金额。"""
    if _constraint_disabled(ctx, "aum_affordability"):
        return RuleOutcome(
            "aum_affordability",
            True,
            "试算已关闭起投能力约束，仅用于对比、不写入正式日批",
        )
    customer = ctx["customer"]
    product = ctx["product"]
    if customer.aum >= product.min_invest:
        return RuleOutcome(
            "aum_affordability",
            True,
            f"客户AUM {customer.aum:.0f} 元覆盖起投金额 {product.min_invest:.0f} 元",
        )
    return RuleOutcome(
        "aum_affordability",
        False,
        f"客户AUM {customer.aum:.0f} 元低于起投金额 {product.min_invest:.0f} 元",
    )


def _check_duration_record(ctx: RuleContext) -> RuleOutcome:
    """记录型：存续期只留痕不拦截（评分口径不校验，产品池以发放为准）。"""
    product = ctx["product"]
    if product.duration_days <= 0:
        return RuleOutcome(
            "duration_valid", True, "记录：开放式存续（duration_days=0）"
        )
    expiry = product.launch_date + timedelta(days=product.duration_days)
    if expiry < ctx["strategy_date"]:
        return RuleOutcome(
            "duration_valid",
            True,
            f"记录：存续期已于 {expiry} 结束"
            "（评分口径不校验存续期，仅记录）",
        )
    return RuleOutcome(
        "duration_valid", True, f"存续期内（至 {expiry}）"
    )


def _check_min_invest_record(ctx: RuleContext) -> RuleOutcome:
    """记录型：起投金额仅展示用，不拦截（题目明确不参与 A2 自动评分）。"""
    budget = ctx.get("invest_budget")
    product = ctx["product"]
    if budget is None:
        return RuleOutcome("min_invest_affordable", True, "未提供预算，仅记录")
    if budget >= product.min_invest:
        return RuleOutcome(
            "min_invest_affordable",
            True,
            f"预算 {budget:.0f} 元满足起投金额 {product.min_invest:.0f} 元",
        )
    return RuleOutcome(
        "min_invest_affordable",
        True,
        f"记录：预算 {budget:.0f} 元低于起投金额 {product.min_invest:.0f} 元"
        "（不参与评分，仅记录）",
    )


# ---------- 渠道类 ----------


def _check_channel_app_requires_app(ctx: RuleContext) -> RuleOutcome:
    if _constraint_disabled(ctx, "channel_app_requires_app"):
        return RuleOutcome(
            "channel_app_requires_app",
            True,
            "试算已关闭 App 安装约束，允许 app_push 参与渠道排序",
        )
    customer = ctx["customer"]
    if ctx.get("channel") == "app_push" and not customer.has_app:
        return RuleOutcome(
            "channel_app_requires_app",
            False,
            "客户未安装 App，不能使用 app_push 渠道",
        )
    return RuleOutcome("channel_app_requires_app", True, "渠道与 App 条件匹配")


def _check_channel_call_complaint_block(ctx: RuleContext) -> RuleOutcome:
    if _constraint_disabled(ctx, "channel_call_complaint_block"):
        return RuleOutcome(
            "channel_call_complaint_block",
            True,
            "试算已关闭投诉外呼约束，允许 call 参与渠道排序",
        )
    behavior = ctx.get("behavior")
    complaints = behavior.complaint_count_90d if behavior is not None else 0
    if ctx.get("channel") == "call" and complaints >= 2:
        return RuleOutcome(
            "channel_call_complaint_block",
            False,
            f"客户近 90 天投诉 {complaints} 次，禁用电话外呼（风险规则，防客诉升级）",
        )
    return RuleOutcome(
        "channel_call_complaint_block", True, "投诉记录未触发外呼限制"
    )


def _check_channel_manager_quota(ctx: RuleContext) -> RuleOutcome:
    if ctx.get("channel") == "manager":
        if not ctx.get("manager_pool_member", False):
            return RuleOutcome(
                "channel_manager_quota",
                False,
                "客户未进入当日经理池快照，不能使用 manager 渠道",
            )
        rank = ctx.get("manager_priority_rank")
        size = ctx.get("manager_pool_size")
        return RuleOutcome(
            "channel_manager_quota",
            True,
            f"客户位于当日经理池快照第 {rank}/{size} 位",
        )
    return RuleOutcome(
        "channel_manager_quota", True, "非 manager 渠道，不占用经理池容量"
    )


def _check_channel_manager_eligible(ctx: RuleContext) -> RuleOutcome:
    if ctx.get("channel") == "manager":
        if not ctx.get("manager_eligible", False):
            return RuleOutcome(
                "channel_manager_eligible",
                False,
                "客户未满足金卡/钻石或 AUM≥50万元的经理池资格",
            )
        return RuleOutcome(
            "channel_manager_eligible",
            True,
            "客户满足金卡/钻石或 AUM≥50万元的经理池资格",
        )
    return RuleOutcome(
        "channel_manager_eligible",
        True,
        "非 manager 渠道",
    )


# ---------- 时段类 ----------


def _check_slot_in_enum(ctx: RuleContext) -> RuleOutcome:
    slot = ctx.get("recommended_time")
    if slot in TIME_SLOTS:
        return RuleOutcome("slot_in_enum", True, "时段在题目规定枚举内")
    return RuleOutcome(
        "slot_in_enum", False, f"非法时段：{slot!r}（须为题目规定枚举）"
    )


# ---------- 话术类 ----------


def _check_script_length(ctx: RuleContext) -> RuleOutcome:
    script = ctx.get("marketing_script", "")
    length = len(script)
    if 10 <= length <= 300:
        return RuleOutcome("script_length", True, f"话术长度 {length} 字符")
    return RuleOutcome(
        "script_length", False, f"话术长度 {length} 字符，须在 [10, 300] 内"
    )


def _check_script_compliance_note(ctx: RuleContext) -> RuleOutcome:
    script = ctx.get("marketing_script", "")
    if COMPLIANCE_NOTE in script:
        return RuleOutcome(
            "script_compliance_note", True, "话术包含合规提示语"
        )
    return RuleOutcome(
        "script_compliance_note", False, "话术缺少合规提示语"
    )


def _check_script_overshoot_warning(ctx: RuleContext) -> RuleOutcome:
    if not ctx.get("overshoot", False):
        return RuleOutcome(
            "script_overshoot_warning", True, "非溢出产品，无需风险提示变体"
        )
    script = ctx.get("marketing_script", "")
    if OVERSHOOT_NOTE in script:
        return RuleOutcome(
            "script_overshoot_warning", True, "溢出产品话术已带风险提示"
        )
    return RuleOutcome(
        "script_overshoot_warning", False, "溢出产品话术缺少风险提示"
    )


# ----------------------------------------------------------------
# 规则目录（顺序即看板展示顺序）
# ----------------------------------------------------------------

RULES = [
    _rule(
        "risk_match",
        "适当性匹配（风险等级）",
        "compliance",
        "产品风险等级最多高于客户风险偏好 1 级，并参与统一概率排序",
        _check_risk_match,
    ),
    _rule(
        "product_launched",
        "产品已成立（as-of）",
        "compliance",
        "产品成立日期不得晚于策略日期",
        _check_product_launched,
    ),
    _rule(
        "customer_registered",
        "客户已注册（as-of）",
        "compliance",
        "客户注册日期不得晚于策略日期",
        _check_customer_registered,
    ),
    _rule(
        "aum_affordability",
        "起投能力校验",
        "batch_compliance",
        "客户AUM必须覆盖产品最低起投金额",
        _check_aum_affordability,
    ),
    _rule(
        "duration_valid",
        "存续期（仅记录）",
        "record",
        "存续期只留痕不拦截：评分口径不校验，产品池以发放为准",
        _check_duration_record,
        hard=False,
    ),
    _rule(
        "min_invest_affordable",
        "起投金额（仅记录）",
        "record",
        "起投金额仅展示用，不参与 A2 自动评分",
        _check_min_invest_record,
        hard=False,
    ),
    _rule(
        "channel_app_requires_app",
        "app_push 需安装 App",
        "channel",
        "未安装 App 的客户不能使用 app_push 渠道",
        _check_channel_app_requires_app,
    ),
    _rule(
        "channel_call_complaint_block",
        "投诉保护（禁用外呼）",
        "channel",
        "近 90 天投诉 ≥2 次的客户禁用 call 渠道（风险规则）",
        _check_channel_call_complaint_block,
    ),
    _rule(
        "channel_manager_quota",
        "当日经理池快照",
        "channel",
        "仅当日高价值客户池成员可使用 manager 渠道",
        _check_channel_manager_quota,
    ),
    _rule(
        "channel_manager_eligible",
        "经理池资格",
        "channel",
        "金卡/钻石或 AUM≥50万元可参与当日经理池排序",
        _check_channel_manager_eligible,
        hard=False,
    ),
    _rule(
        "slot_in_enum",
        "时段枚举校验",
        "timing",
        "recommended_time 必须是题目规定的 5 个时段之一",
        _check_slot_in_enum,
    ),
    _rule(
        "script_length",
        "话术长度校验",
        "script",
        "marketing_script 字符数须在 [10, 300] 内",
        _check_script_length,
    ),
    _rule(
        "script_compliance_note",
        "话术合规提示语",
        "script",
        "话术必须包含合规提示语（理财非存款，产品有风险，投资须谨慎）",
        _check_script_compliance_note,
    ),
    _rule(
        "script_overshoot_warning",
        "溢出产品风险提示",
        "script",
        "风险溢出产品的话术必须包含谨慎选择提示",
        _check_script_overshoot_warning,
    ),
]


def build_default_engine():
    """构造默认规则引擎（含全部 14 条规则）。"""
    from .engine import RuleEngine

    return RuleEngine(RULES)
