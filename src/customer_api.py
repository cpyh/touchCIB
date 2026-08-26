"""客户画像与风险评估 API（由 liantiao 分支 backend/ 统一到本服务）。

- 接口契约与前端 shared/customer-api.ts 完全一致（envelope: {code, message, data}）；
- 表映射：t_customer → ods_customer、t_holding → ods_holding、
  t_product → ods_product、t_event → ods_event（复用现有 MySQL 表）；
- 风险评估为规则打分（年龄/收入/职业/AUM → R1~R5）；
- AI 摘要默认模板模式（AI_SUMMARY_MODE=remote 时可切换远程模型）。
"""

from __future__ import annotations

import json
import os
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pymysql
from flask import Blueprint, jsonify, request

from .database import database_connection

# ----------------------------------------------------------------
# 错误类型与校验
# ----------------------------------------------------------------


class ValidationError(ValueError):
    """请求数据不合法。"""


class NotFoundError(LookupError):
    """业务对象不存在。"""


class ServiceError(RuntimeError):
    """数据库或上游服务失败。"""


class UpstreamError(ServiceError):
    """外部 AI 服务失败。"""


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


# ----------------------------------------------------------------
# 风险评估（规则打分，与 liantiao backend/app/risk.py 一致）
# ----------------------------------------------------------------

AGE_SCORE = {
    "18-24": 8, "25-34": 10, "35-44": 6, "45-54": 0, "55-64": -8, "65+": -15,
}
INCOME_SCORE = {"10万以下": -10, "10-30万": 0, "30-50万": 8, "50万以上": 15}
OCCUPATION_SCORE = {
    "退休": -8, "个体经营": 5, "专业技术": 3, "企业职员": 0, "公务员": 0, "其他": 0,
}
RISK_LABELS = {
    "R1": "谨慎型", "R2": "稳健型", "R3": "平衡型", "R4": "成长型", "R5": "进取型",
}


def _aum_score(aum: Decimal) -> int:
    if aum < Decimal("100000"):
        return -8
    if aum < Decimal("500000"):
        return 0
    if aum < Decimal("1000000"):
        return 5
    return 10


def assess_risk(payload: dict) -> str:
    score = 50
    score += AGE_SCORE[payload["age_group"]]
    score += INCOME_SCORE[payload["income_level"]]
    score += OCCUPATION_SCORE[payload["occupation"]]
    score += _aum_score(Decimal(str(payload["aum"])))
    score = max(0, min(100, score))

    if score <= 25:
        return "R1"
    if score <= 40:
        return "R2"
    if score <= 60:
        return "R3"
    if score <= 75:
        return "R4"
    return "R5"


def risk_label(level: str) -> str:
    return RISK_LABELS.get(level, level)


# ----------------------------------------------------------------
# 配置（AI 摘要模式与画像 as-of）
# ----------------------------------------------------------------

PROFILE_AS_OF_DATE = date.fromisoformat(
    os.getenv("PROFILE_AS_OF_DATE", "2026-03-31")
)


# ----------------------------------------------------------------
# 客户服务（t_customer → ods_customer）
# ----------------------------------------------------------------

ZERO = Decimal("0")


def _customer_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"C{timestamp}{secrets.randbelow(100000):05d}"


def customer_dict(row: dict) -> dict:
    return {
        "customer_id": row["customer_id"],
        "age_group": row["age_group"],
        "city": row["city"],
        "occupation": row["occupation"],
        "income_level": row["income_level"],
        "register_date": row["register_date"].isoformat(),
        "aum": float(row["aum"]),
        "risk_appetite": row["risk_appetite"],
        "risk_label": risk_label(row["risk_appetite"]),
        "vip_level": row["vip_level"],
        "has_app": bool(row["has_app"]),
    }


def list_customers(
    *,
    page: int,
    page_size: int,
    keyword: str | None,
    risk_appetite: str | None,
    vip_level: str | None,
    city: str | None,
) -> dict:
    if not isinstance(page, int) or page < 1:
        raise ValidationError("page must be greater than or equal to 1")
    if not isinstance(page_size, int) or page_size < 1 or page_size > 100:
        raise ValidationError("page_size must be between 1 and 100")
    if risk_appetite and risk_appetite not in RISK_LEVELS:
        raise ValidationError("invalid risk_appetite")
    if vip_level and vip_level not in VIP_LEVELS:
        raise ValidationError("invalid vip_level")

    clauses: list[str] = []
    params: list[object] = []
    if keyword:
        clauses.append(
            "(customer_id LIKE %s OR city LIKE %s OR occupation LIKE %s)"
        )
        search = f"%{keyword.strip()}%"
        params.extend([search, search, search])
    if risk_appetite:
        clauses.append("risk_appetite = %s")
        params.append(risk_appetite)
    if vip_level:
        clauses.append("vip_level = %s")
        params.append(vip_level)
    if city:
        clauses.append("city = %s")
        params.append(city.strip())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size

    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) AS total FROM ods_customer {where_sql}",
                    params,
                )
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"""
                    SELECT customer_id, age_group, city, occupation, income_level,
                           register_date, aum, risk_appetite, vip_level, has_app
                    FROM ods_customer
                    {where_sql}
                    ORDER BY customer_id
                    LIMIT %s OFFSET %s
                    """,
                    [*params, page_size, offset],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query customers") from exc

    return {
        "items": [customer_dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_customer(raw_payload: object) -> dict:
    payload = validate_customer_create(raw_payload)
    risk_appetite = assess_risk(payload)

    for _ in range(3):
        customer_id = _customer_id()
        try:
            connection = database_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO ods_customer (
                            customer_id, age_group, city, occupation, income_level,
                            register_date, aum, risk_appetite, vip_level, has_app
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            customer_id,
                            payload["age_group"],
                            payload["city"],
                            payload["occupation"],
                            payload["income_level"],
                            payload["register_date"],
                            payload["aum"],
                            risk_appetite,
                            payload["vip_level"],
                            payload["has_app"],
                        ),
                    )
                connection.commit()
            finally:
                connection.close()
            row = {
                "customer_id": customer_id,
                **payload,
                "risk_appetite": risk_appetite,
            }
            return customer_dict(row)
        except pymysql.err.IntegrityError as exc:
            if exc.args and exc.args[0] == 1062:
                continue
            raise ServiceError("unable to create customer") from exc
        except (pymysql.MySQLError, OSError, ValueError) as exc:
            raise ServiceError("unable to create customer") from exc

    raise ServiceError("unable to generate a unique customer id")


# ----------------------------------------------------------------
# 画像服务（t_holding/t_product/t_event → ods_*）
# ----------------------------------------------------------------


def _ratio(value: Decimal, total: Decimal) -> float | None:
    if total == 0:
        return None
    return float((value / total).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _distribution(amounts: dict[str, Decimal], total: Decimal) -> list[dict]:
    return [
        {"name": name, "amount": float(amount), "ratio": _ratio(amount, total)}
        for name, amount in sorted(amounts.items())
    ]


def build_asset_profile(customer: dict, rows: list[dict]) -> dict:
    total = sum((row["amount"] for row in rows), ZERO)
    type_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    risk_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    liquid_amount = ZERO
    weighted_return = ZERO

    holdings = []
    for row in rows:
        amount = row["amount"]
        type_amounts[row["product_type"]] += amount
        risk_amounts[row["risk_level"]] += amount
        if row["liquidity"] in {"T+0", "T+1"}:
            liquid_amount += amount
        weighted_return += amount * row["expected_return"]
        holdings.append(
            {
                "holding_id": row["holding_id"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "product_type": row["product_type"],
                "risk_level": row["risk_level"],
                "liquidity": row["liquidity"],
                "amount": float(amount),
                "buy_date": row["buy_date"].isoformat(),
                "expected_return": float(row["expected_return"]),
            }
        )

    return {
        "aum": float(customer["aum"]),
        "holding_amount": float(total),
        "holding_product_count": len({row["product_id"] for row in rows}),
        "product_type_distribution": _distribution(type_amounts, total),
        "risk_distribution": _distribution(risk_amounts, total),
        "high_liquidity_ratio": _ratio(liquid_amount, total),
        "weighted_expected_return": _ratio(weighted_return, total),
        "holdings": holdings,
    }


def build_behavior_profile(
    customer: dict, events: list[dict], asset_profile: dict, as_of_date
) -> dict:
    total_counts = Counter(event["event_type"] for event in events)
    recent_start = as_of_date - timedelta(days=29)
    recent_counts = Counter(
        event["event_type"]
        for event in events
        if event["event_date"] >= recent_start
    )
    latest = max(events, key=lambda event: event["event_date"]) if events else None

    tags: list[str] = []
    if customer["aum"] >= Decimal("1000000"):
        tags.append("高净值客户")
    if customer["risk_appetite"] in {"R1", "R2"}:
        tags.append("偏好稳健")
    if customer["has_app"]:
        tags.append("数字渠道客户")
    if (asset_profile["high_liquidity_ratio"] or 0) >= 0.5:
        tags.append("重视流动性")
    if sum(recent_counts.values()) >= 5:
        tags.append("近期活跃")
    if recent_counts["complaint"] > 0:
        tags.append("需要重点维护")

    return {
        "total_counts": {
            name: total_counts[name] for name in ("login", "consult", "complaint")
        },
        "recent_30d_counts": {
            name: recent_counts[name] for name in ("login", "consult", "complaint")
        },
        "latest_event_type": latest["event_type"] if latest else None,
        "latest_event_date": latest["event_date"].isoformat() if latest else None,
        "tags": tags,
    }


def get_customer_profile(customer_id: str) -> dict:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM ods_customer WHERE customer_id = %s",
                    (customer_id,),
                )
                customer = cursor.fetchone()
                if customer is None:
                    raise NotFoundError("customer not found")

                as_of_date = max(PROFILE_AS_OF_DATE, customer["register_date"])
                cursor.execute(
                    """
                    SELECT h.holding_id, h.product_id, h.amount, h.buy_date,
                           p.product_name, p.product_type, p.risk_level,
                           p.liquidity, p.expected_return
                    FROM ods_holding h
                    JOIN ods_product p ON p.product_id = h.product_id
                    WHERE h.customer_id = %s AND h.buy_date <= %s
                    ORDER BY h.amount DESC, h.holding_id
                    """,
                    (customer_id, as_of_date),
                )
                holdings = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT event_type, event_date
                    FROM ods_event
                    WHERE customer_id = %s AND event_date <= %s
                    ORDER BY event_date DESC, event_id DESC
                    """,
                    (customer_id, as_of_date),
                )
                events = cursor.fetchall()
        finally:
            connection.close()
    except NotFoundError:
        raise
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to query customer profile") from exc

    asset_profile = build_asset_profile(customer, holdings)
    behavior_profile = build_behavior_profile(
        customer, events, asset_profile, as_of_date
    )
    basic = customer_dict(customer)
    return {
        "as_of_date": as_of_date.isoformat(),
        "basic_info": basic,
        "asset_profile": asset_profile,
        "behavior_profile": behavior_profile,
        "ai_summary": parse_cached_analysis(customer.get("ai_summary")),
        "ai_summary_generated_at": (
            customer["ai_summary_generated_at"].isoformat()
            if customer.get("ai_summary_generated_at")
            else None
        ),
    }


# ----------------------------------------------------------------
# AI 画像分析（结构化输出，与 liantiao backend/app/ai_analysis.py 一致）
# ----------------------------------------------------------------

ANALYSIS_FIELDS = ("overview", "insight", "suggestion")


def normalize_analysis(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("AI analysis must be a JSON object")

    analysis: dict[str, object] = {}
    for field in ANALYSIS_FIELDS:
        text = value.get(field)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"AI analysis field {field} is missing")
        analysis[field] = text.strip()

    combined = "".join(str(analysis[field]) for field in ANALYSIS_FIELDS)
    raw_highlights = value.get("highlights", [])
    if not isinstance(raw_highlights, list):
        raw_highlights = []

    highlights: list[str] = []
    for item in raw_highlights:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if not term or len(term) > 12 or term not in combined or term in highlights:
            continue
        highlights.append(term)
        if len(highlights) == 5:
            break
    analysis["highlights"] = highlights
    return analysis


def parse_cached_analysis(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        return normalize_analysis(json.loads(value))
    except (json.JSONDecodeError, ValueError, TypeError):
        return {
            "overview": value.strip(),
            "insight": "历史总结未包含结构化需求洞察。",
            "suggestion": "可重新生成总结以获得完整的客户画像分析。",
            "highlights": [],
        }


# ----------------------------------------------------------------
# AI 摘要（DeepSeek 优先，未配置密钥时回退本地模板）
# ----------------------------------------------------------------


def _preferred_type(profile: dict) -> str | None:
    items = profile["asset_profile"]["product_type_distribution"]
    return max(items, key=lambda item: item["amount"])["name"] if items else None


def _template_analysis(profile: dict) -> dict:
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
    overview = (
        f"该客户为{basic['vip_level']}客户，资产管理规模{basic['aum']:,.2f}元，"
        f"风险偏好为{basic['risk_label']}。{asset_text}{preference_text}。"
    )
    insight = f"画像标签：{tags}。{behavior_text}。"
    suggestion = (
        "建议围绕资金使用周期与收益目标进一步了解需求，"
        "并结合渠道偏好安排持续服务。本总结仅用于画像展示，不构成投资建议。"
    )
    combined = overview + insight + suggestion
    highlights = [
        tag for tag in behavior["tags"][:3] if tag and tag in combined
    ]
    return {
        "overview": overview,
        "insight": insight,
        "suggestion": suggestion,
        "highlights": highlights,
    }


def _deepseek_analysis(profile: dict) -> dict:
    try:
        from openai import OpenAI, OpenAIError  # 延迟导入，未装 openai 时不影响其他端点
    except ImportError as exc:
        raise UpstreamError("openai SDK is not installed") from exc

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise UpstreamError("DEEPSEEK_API_KEY is not configured")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))

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
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        response = client.chat.completions.create(
            model=model,
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
    return analysis, model


def generate_ai_summary(customer_id: str) -> dict:
    profile = get_customer_profile(customer_id)
    if os.getenv("DEEPSEEK_API_KEY"):
        analysis, model = _deepseek_analysis(profile)
        provider = "deepseek"
    else:
        analysis = _template_analysis(profile)
        provider = "template"
        model = "rules-template"
    cached_value = json.dumps(analysis, ensure_ascii=False)
    generated_at = datetime.now()
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ods_customer
                    SET ai_summary = %s, ai_summary_generated_at = %s
                    WHERE customer_id = %s
                    """,
                    (cached_value, generated_at, customer_id),
                )
            connection.commit()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ServiceError("unable to save AI summary") from exc
    return {
        "customer_id": customer_id,
        "analysis": analysis,
        "generated_at": generated_at.isoformat(),
        "provider": provider,
        "model": model,
    }


# ----------------------------------------------------------------
# 路由（/api/v1/customers，契约与前端 shared/customer-api.ts 一致）
# ----------------------------------------------------------------

customers_bp = Blueprint("customers_v1", __name__, url_prefix="/api/v1/customers")


def success(data, status: int = 200):
    return jsonify({"code": 0, "message": "success", "data": data}), status


@customers_bp.get("")
def customers_list():
    return success(
        list_customers(
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=20, type=int),
            keyword=request.args.get("keyword"),
            risk_appetite=request.args.get("risk_appetite"),
            vip_level=request.args.get("vip_level"),
            city=request.args.get("city"),
        )
    )


@customers_bp.post("")
def customer_create():
    return success(create_customer(request.get_json(silent=True)), 201)


@customers_bp.get("/<customer_id>/profile")
def customer_profile(customer_id: str):
    return success(get_customer_profile(customer_id))


@customers_bp.post("/<customer_id>/ai-summary")
def customer_ai_summary(customer_id: str):
    return success(generate_ai_summary(customer_id))


@customers_bp.errorhandler(ValidationError)
def handle_validation_error(exc):
    return jsonify({"code": 400, "message": str(exc), "data": None}), 400


@customers_bp.errorhandler(NotFoundError)
def handle_not_found(exc):
    return jsonify({"code": 404, "message": str(exc), "data": None}), 404


@customers_bp.errorhandler(UpstreamError)
def handle_upstream_error(exc):
    return jsonify({"code": 502, "message": str(exc), "data": None}), 502


@customers_bp.errorhandler(ServiceError)
def handle_service_error(exc):
    return jsonify({"code": 503, "message": str(exc), "data": None}), 503
