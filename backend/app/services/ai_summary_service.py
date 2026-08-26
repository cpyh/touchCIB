from __future__ import annotations

import json
from datetime import datetime

import pymysql
from openai import OpenAI, OpenAIError

from ..ai_analysis import normalize_analysis
from ..config import settings
from ..db import transaction
from ..errors import ServiceError, UpstreamError
from .profile_service import get_customer_profile


def _deepseek_summary(profile: dict) -> dict:
    if not settings.deepseek_api_key:
        raise UpstreamError("DEEPSEEK_API_KEY is not configured")

    compact_profile = {
        "basic_info": {
            key: value
            for key, value in profile["basic_info"].items()
            if key != "customer_id"
        },
        "asset_profile": {
            key: value
            for key, value in profile["asset_profile"].items()
            if key != "holdings"
        },
        "behavior_profile": profile["behavior_profile"],
    }
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.deepseek_timeout_seconds,
    )
    try:
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一名银行财富管理运营分析助手。你的任务不是复述字段，而是从客户数据中"
                        "提炼对客户经理有用的画像。overview、insight和suggestion三段正文合计控制"
                        "在160至240个中文字符。"
                        "画像概述应概括客户最显著的资产配置、风险偏好和行为特征；需求洞察应把不同"
                        "特征理解为客户可能同时存在的复合需求，例如进取型风险偏好与高流动性持仓可"
                        "表述为兼顾收益弹性和资金灵活性，不得描述为矛盾、偏离或不符合常见逻辑。"
                        "服务建议应给出1至2项适合客户经理执行的需求了解、沟通或持续服务动作，但不得"
                        "直接推荐具体产品。请将输入字段视为当前有效事实，不得质疑数据正确性，不得"
                        "建议核实产品等级、收益参数或数据录入，不得根据外部常识重新判断产品属性。"
                        "全文最多引用3个关键数字，不得逐项罗列基础资料，不得评价无关的缺失字段。"
                        "只能使用输入中的事实，不得虚构因果，不得承诺收益，不得给出投资指令。"
                        "加权预期收益率并非画像重点，通常无需引用；如引用必须说明不代表未来收益。"
                        "数据不足时，只说明可进一步了解客户需求，不评价数据质量。"
                        "请只返回合法json对象，不要返回Markdown、代码块或额外说明。json必须包含"
                        "overview、insight、suggestion和highlights四个字段。highlights选择3至5个"
                        "最能代表客户特征的短语，每个短语不超过12个中文字符，必须原样出现在前三段"
                        "正文中；不要选择城市、年龄和职业等普通基础信息。"
                        "参考案例json：{\"overview\":\"客户风险偏好进取，当前配置以现金管理为主，"
                        "整体重视资金灵活性。\",\"insight\":\"高流动性持仓与进取型风险偏好体现出"
                        "兼顾资金灵活性和收益弹性的复合需求。\",\"suggestion\":\"建议围绕近期咨询"
                        "了解资金使用周期和收益目标，并通过线上渠道持续提供配置沟通。\","
                        "\"highlights\":[\"进取型风险偏好\",\"高流动性持仓\",\"近期咨询\","
                        "\"线上渠道\"]}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请基于以下结构化数据生成客户画像，提炼客户的配置特点、潜在需求和适合的"
                        "服务方式，不要检查数据异常，也不要逐项复述：\n"
                        + json.dumps(compact_profile, ensure_ascii=False)
                    ),
                },
            ],
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
            response_format={"type": "json_object"},
            max_tokens=600,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("empty content")
        analysis = normalize_analysis(json.loads(content))
    except (OpenAIError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise UpstreamError("DeepSeek summary service is unavailable") from exc
    return analysis


def generate_ai_summary(customer_id: str) -> dict:
    profile = get_customer_profile(customer_id)
    analysis = _deepseek_summary(profile)
    cached_value = json.dumps(analysis, ensure_ascii=False)
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
                    (cached_value, generated_at, customer_id),
                )
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to save AI summary") from exc
    return {
        "customer_id": customer_id,
        "analysis": analysis,
        "generated_at": generated_at.isoformat(),
        "provider": "deepseek",
        "model": settings.deepseek_model,
    }
