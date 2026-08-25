"""话术模板渲染：分渠道语态 + 合规提示语 + 溢出风险提示。"""

from __future__ import annotations

from .models import Customer, Product

COMPLIANCE_NOTE = "理财非存款，产品有风险，投资须谨慎。"
OVERSHOOT_NOTE = "该产品风险等级高于您的风险偏好，请谨慎选择。"

LIQUIDITY_TEXT = {
    "T+0": "T+0 随时赎回",
    "T+1": "T+1 次日赎回",
    "封闭": "封闭运作",
}

_CHANNEL_PREFIX = {
    "sms": "【智能财富】尊敬的{city}客户，为您推荐",
    "app_push": "专属推荐",
    "call": "您好，我是您的专属理财顾问，为您介绍",
    "manager": "{vip}贵宾专享",
}

_CHANNEL_SUFFIX = {
    "sms": "",
    "app_push": "",
    "call": "",
    "manager": "，可为您预约专属认购",
}


def _fmt_return(product: Product) -> str:
    return f"{product.expected_return * 100:.1f}%"


def _fmt_duration(product: Product) -> str:
    if product.duration_days <= 0:
        return "灵活存续"
    return f"{product.duration_days}天"


def _fmt_amount(product: Product) -> str:
    return f"{product.min_invest:.0f}"


def build_sales_script(
    customer: Customer, product: Product, channel: str
) -> str:
    """生成销售主体话术（不含合规提示语）。"""
    if channel not in _CHANNEL_PREFIX:
        raise ValueError(f"unknown channel: {channel}")
    prefix = _CHANNEL_PREFIX[channel].format(
        city=customer.city, vip=customer.vip_level
    )
    suffix = _CHANNEL_SUFFIX[channel]
    body = (
        f"{product.product_name}（{product.risk_level}·{product.product_type}），"
        f"业绩比较基准{_fmt_return(product)}，{_fmt_duration(product)}，"
        f"{_fmt_amount(product)}元起投，{LIQUIDITY_TEXT.get(product.liquidity, product.liquidity)}"
    )
    return f"{prefix}：{body}{suffix}。"


def enforce_length(
    sales_script: str, *, overshoot: bool
) -> str:
    """保证整段话术（含提示语）不超过 300 字符，合规提示语永不删除。"""
    tails = COMPLIANCE_NOTE
    if overshoot:
        tails = f"{OVERSHOOT_NOTE}{COMPLIANCE_NOTE}"
    budget = 300 - len(tails) - 1
    if len(sales_script) > budget:
        sales_script = sales_script[: max(budget - 1, 0)] + "…"
    return f"{sales_script}{tails}"


def build_script(
    customer: Customer, product: Product, channel: str, *, overshoot: bool
) -> str:
    """渲染完整话术（销售主体 + 溢出提示 + 合规提示），长度必在 [10, 300]。"""
    return enforce_length(
        build_sales_script(customer, product, channel), overshoot=overshoot
    )
