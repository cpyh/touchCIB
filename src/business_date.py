"""统一业务日期口径：页面快照、日批和ADS查询共用。"""

from __future__ import annotations

from datetime import date


DEFAULT_BUSINESS_DATE = date(2026, 4, 15)


def parse_business_date(
    value: object | None,
    *,
    default: date = DEFAULT_BUSINESS_DATE,
) -> date:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ValueError("business_date 必须是 YYYY-MM-DD 格式")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("business_date 必须是有效的 YYYY-MM-DD 日期") from exc
    if value != parsed.isoformat():
        raise ValueError("business_date 必须是 YYYY-MM-DD 格式")
    return parsed


__all__ = ["DEFAULT_BUSINESS_DATE", "parse_business_date"]
