from __future__ import annotations

import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pymysql

from ..config import settings
from ..db import transaction
from ..errors import ServiceError, UpstreamError
from .profile_service import get_customer_profile


def _preferred_type(profile: dict) -> str | None:
    items = profile["asset_profile"]["product_type_distribution"]
    return max(items, key=lambda item: item["amount"])["name"] if items else None


def _template_summary(profile: dict) -> str:
    basic = profile["basic_info"]
    assets = profile["asset_profile"]
    behavior = profile["behavior_profile"]
    preferred_type = _preferred_type(profile)
    event_total = sum(behavior["recent_30d_counts"].values())
    asset_text = (
        f"当前可识别产品持仓{assets['holding_amount']:,.2f}元，共"
        f"{assets['holding_product_count']}类产品"
        if assets["holding_product_count"]
        else "当前暂无可识别产品持仓"
    )
    preference_text = f"，持仓以{preferred_type}类产品为主" if preferred_type else ""
    behavior_text = (
        f"近30天记录到{event_total}次行为，近期互动较为活跃"
        if event_total >= 5
        else f"近30天记录到{event_total}次行为"
    )
    tags = "、".join(behavior["tags"][:3]) or "暂无明显行为标签"
    return (
        f"该客户为{basic['vip_level']}客户，资产管理规模{basic['aum']:,.2f}元，"
        f"风险偏好为{basic['risk_label']}。{asset_text}{preference_text}；"
        f"{behavior_text}。当前画像标签为{tags}。本总结仅用于客户画像展示，不构成投资建议。"
    )


def _remote_summary(profile: dict) -> str:
    if not settings.ai_api_url or not settings.ai_api_key or not settings.ai_model:
        raise UpstreamError("AI remote mode is not fully configured")
    compact_profile = {
        "basic_info": profile["basic_info"],
        "asset_profile": {
            key: value
            for key, value in profile["asset_profile"].items()
            if key != "holdings"
        },
        "behavior_profile": profile["behavior_profile"],
    }
    prompt = (
        "请根据以下结构化客户画像生成100至200个中文字符的客观总结。"
        "不得虚构事实，不得承诺收益，不得给出具体投资指令；数据不足时明确说明。\n"
        + json.dumps(compact_profile, ensure_ascii=False)
    )
    body = json.dumps(
        {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": "你是银行客户画像摘要助手。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        settings.ai_api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.ai_timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
        summary = result["choices"][0]["message"]["content"].strip()
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise UpstreamError("AI summary service is unavailable") from exc
    if not summary:
        raise UpstreamError("AI summary service returned empty content")
    return summary


def generate_ai_summary(customer_id: str) -> dict:
    profile = get_customer_profile(customer_id)
    if settings.ai_summary_mode == "remote":
        summary = _remote_summary(profile)
        mode = "remote"
    else:
        summary = _template_summary(profile)
        mode = "template"
    generated_at = datetime.now()
    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE t_customer
                    SET ai_summary = %s, ai_summary_generated_at = %s
                    WHERE customer_id = %s
                    """,
                    (summary, generated_at, customer_id),
                )
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to save AI summary") from exc
    return {
        "customer_id": customer_id,
        "ai_summary": summary,
        "generated_at": generated_at.isoformat(),
        "mode": mode,
    }
