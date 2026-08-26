from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from .errors import ValidationError


AGE_GROUPS = {"18-24", "25-34", "35-44", "45-54", "55-64", "65+"}
OCCUPATIONS = {"专业技术", "个体经营", "企业职员", "公务员", "其他", "退休"}
INCOME_LEVELS = {"10万以下", "10-30万", "30-50万", "50万以上"}
VIP_LEVELS = {"普通", "银卡", "金卡", "钻石"}
RISK_LEVELS = {"R1", "R2", "R3", "R4", "R5"}


def _required_text(payload: dict, field: str, *, max_length: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"{field} is too long")
    return value


def _enum(payload: dict, field: str, allowed: set[str]) -> str:
    value = _required_text(payload, field, max_length=32)
    if value not in allowed:
        raise ValidationError(f"invalid {field}")
    return value


def validate_customer_create(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")

    try:
        register_date = date.fromisoformat(str(payload.get("register_date", "")))
    except ValueError as exc:
        raise ValidationError("register_date must use YYYY-MM-DD") from exc
    if register_date > date.today():
        raise ValidationError("register_date cannot be later than today")

    try:
        aum = Decimal(str(payload.get("aum")))
    except (InvalidOperation, TypeError) as exc:
        raise ValidationError("aum must be a number") from exc
    if not aum.is_finite() or aum < 0:
        raise ValidationError("aum must be greater than or equal to 0")
    if -aum.as_tuple().exponent > 2:
        raise ValidationError("aum supports at most two decimal places")

    has_app = payload.get("has_app")
    if not isinstance(has_app, bool):
        raise ValidationError("has_app must be boolean")

    return {
        "age_group": _enum(payload, "age_group", AGE_GROUPS),
        "city": _required_text(payload, "city", max_length=50),
        "occupation": _enum(payload, "occupation", OCCUPATIONS),
        "income_level": _enum(payload, "income_level", INCOME_LEVELS),
        "register_date": register_date,
        "aum": aum,
        "vip_level": _enum(payload, "vip_level", VIP_LEVELS),
        "has_app": has_app,
    }
