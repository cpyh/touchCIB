"""营销触达事件服务：埋点写入（含归因校验）、事件查询与状态推导。

事件模型（docs/demo-design.md §2）：
- append-only，永不 UPDATE/DELETE；
- sent 事件：运营标记"已触达"；
- responded 事件：购买事实经归因规则校验后写入；
- "待执行"不存储——策略存在且无任何事件即推导得出。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pandas as pd
import pymysql

from .business_date import DEFAULT_BUSINESS_DATE
from .database import database_connection
from .marketing.attribution import DEFAULT_WINDOW_DAYS, attribute_purchase
from .marketing.templates import COMPLIANCE_NOTE

STRATEGY_ID_PATTERN = re.compile(r"^(?P<customer_id>[^:]+):(?P<rank>[123])$")


class CampaignInputError(ValueError):
    """埋点请求不合法（业务校验失败）。"""


class CampaignStoreError(RuntimeError):
    """事件数据无法访问。"""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _event_json(row: dict) -> dict:
    return {key: _json_value(value) for key, value in row.items()}


def load_strategy_frame(
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> pd.DataFrame:
    """兼容分析/导出调用方：返回指定业务日的提交形状。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT customer_id, strategy_rank AS `rank`, product_id, "
                    "recommended_channel, recommended_time, marketing_script "
                    "FROM ads_marketing_strategy WHERE strategy_date = %s "
                    "ORDER BY customer_id, strategy_rank",
                    (business_date,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query ADS strategies") from exc
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["rank"] = frame["rank"].astype(str)
    return frame


def strategy_top3(
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict[str, tuple[str, str, str]]:
    """指定ADS批次的 customer_id -> (rank1, rank2, rank3)。"""
    frame = load_strategy_frame(business_date)
    result: dict[str, tuple[str, str, str]] = {}
    for customer_id, group in frame.groupby("customer_id", sort=False):
        ranks = group["rank"].tolist()
        ordered = group.sort_values("rank")["product_id"].tolist()
        if len(group) != 3 or set(ranks) != {"1", "2", "3"}:
            raise CampaignStoreError(
                f"客户 {customer_id} 的ADS策略必须恰好包含rank 1/2/3"
            )
        if len(set(ordered)) != 3:
            raise CampaignStoreError(
                f"客户 {customer_id} 的ADS Top3产品不得重复"
            )
        result[customer_id] = tuple(ordered)
    return result


def strategy_date(business_date: date = DEFAULT_BUSINESS_DATE) -> date:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT strategy_date FROM ads_marketing_strategy "
                    "WHERE strategy_date=%s LIMIT 1",
                    (business_date,),
                )
                row = cursor.fetchone() or {}
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query latest strategy date") from exc
    value = row.get("strategy_date")
    if value is None:
        raise CampaignStoreError("营销ADS批处理尚未生成策略")
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _known_customer_ids(
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> frozenset[str]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT customer_id FROM dwd_dim_customer WHERE register_date <= %s",
                    (business_date,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query DWD customers") from exc
    return frozenset(str(row["customer_id"]) for row in rows)


def _stored_strategy_rows(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> list[dict]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT strategy_id, customer_id, strategy_rank AS `rank`, strategy_date, "
                    "product_id, recommended_channel, recommended_time, "
                    "marketing_script, a1_probability AS model_prob, "
                    "a1_rank, rule_trace_json, selection_reason, model_version, "
                    "rule_version, batch_id, generated_at AS created_at "
                    "FROM ads_marketing_strategy "
                    "WHERE customer_id = %s AND strategy_date = %s "
                    "ORDER BY strategy_rank",
                    (customer_id, business_date),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query ADS strategy snapshot") from exc
    return list(rows)


def _require_strategy_rows(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> list[dict]:
    """读取客户ADS批处理结果，并校验Top3已完整生成。"""
    if customer_id not in _known_customer_ids(business_date):
        raise CampaignInputError(f"客户 {customer_id} 不存在")
    rows = _stored_strategy_rows(customer_id, business_date)
    if len(rows) != 3:
        raise CampaignStoreError(
            f"客户 {customer_id} 的ADS Top3未就绪，请先运行营销批处理"
        )
    return rows


def customer_strategy_date(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> date:
    """读取客户指定ADS策略日期。"""
    if customer_id not in _known_customer_ids(business_date):
        raise CampaignInputError(f"客户 {customer_id} 不存在")
    rows = _require_strategy_rows(customer_id, business_date)
    value = rows[0]["strategy_date"]
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def customer_top3(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> tuple[str, str, str]:
    """取得客户指定ADS批处理Top3。"""
    rows = _require_strategy_rows(customer_id, business_date)
    products = tuple(row["product_id"] for row in rows)
    if len(products) != 3:
        raise CampaignStoreError(f"客户 {customer_id} 的ADS策略没有恰好3个产品")
    return products


def customer_strategy_channel(
    customer_id: str,
    rank: int,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> str:
    """取得某条策略的执行渠道，供KPI与演示归因共用。"""
    for item in _require_strategy_rows(customer_id, business_date):
        if int(item["rank"]) == rank:
            return str(item["recommended_channel"])
    raise CampaignInputError(f"策略不存在：{customer_id}:{rank}")


def _parse_strategy_id(strategy_id: str) -> tuple[str, int]:
    match = STRATEGY_ID_PATTERN.fullmatch(strategy_id or "")
    if not match:
        raise CampaignInputError(
            f"strategy_id 格式须为 {{customer_id}}:{{rank}}（rank 1-3），收到 {strategy_id!r}"
        )
    customer_id = match.group("customer_id")
    rank = int(match.group("rank"))
    if customer_id not in _known_customer_ids():
        raise CampaignInputError(f"策略不存在：{strategy_id}（客户不存在）")
    # 批处理必须已生成完整Top3；请求阶段不再执行算法。
    customer_top3(customer_id)
    return customer_id, rank


def _record_event(
    *,
    strategy_id: str,
    event_type: str,
    occurred_at: datetime,
    product_id: str | None = None,
    amount: float | None = None,
) -> dict:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO app_campaign_event "
                    "(strategy_id, event_type, occurred_at, product_id, amount) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (strategy_id, event_type, occurred_at, product_id, amount),
                )
                cursor.execute(
                    "SELECT campaign_event_id, strategy_id, event_type, "
                    "occurred_at, product_id, amount, created_at "
                    "FROM app_campaign_event WHERE campaign_event_id = LAST_INSERT_ID()"
                )
                row = cursor.fetchone()
            connection.commit()
        finally:
            connection.close()
    except pymysql.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062 and event_type == "responded":
            raise CampaignInputError(
                f"策略 {strategy_id} 已有 responded 事件，重复购买只记首次"
            ) from exc
        raise CampaignStoreError("unable to record campaign event") from exc
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to record campaign event") from exc
    if row is None:
        raise CampaignStoreError("recorded campaign event was not found")
    return _event_json(row)


def _existing_responded(strategy_id: str) -> bool:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM app_campaign_event "
                    "WHERE strategy_id = %s AND event_type = 'responded'",
                    (strategy_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query campaign events") from exc
    return int(row["count"]) > 0


def create_sent_event(
    strategy_id: str,
    occurred_at: datetime | None = None,
) -> dict:
    """标记"已触达"：写入 sent 事件。

    口径：工作面板面向客户，一客户一次触达。
    strategy_id 仅标注本次执行的首选策略，同一客户重复触达被拒绝。
    """
    customer_id, _ = _parse_strategy_id(strategy_id)
    existing = list_campaign_events(customer_id=customer_id)
    if any(event["event_type"] == "sent" for event in existing):
        raise CampaignInputError(
            f"客户 {customer_id} 已触达：按客户口径一次营销活动只触达一次，"
            "请直接跟进后续动作"
        )
    return _record_event(
        strategy_id=strategy_id,
        event_type="sent",
        occurred_at=occurred_at or datetime.now(),
    )


def create_responded_event(
    *,
    customer_id: str,
    product_id: str,
    buy_date: date,
    amount: float | None = None,
    occurred_at: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """标记"已响应"：购买事实过归因校验后写入 responded 事件。

    校验顺序（任一不通过返回 CampaignInputError，由调用方映射 422）：
    1. 归因规则：窗口 + Top3 匹配（attribution.attribute_purchase）
    2. 重复购买只记首次：该策略已有 responded 事件则拒绝
    """
    if not customer_id:
        raise CampaignInputError("customer_id 不能为空")
    if not product_id:
        raise CampaignInputError("product_id 不能为空")
    if (
        isinstance(window_days, bool)
        or not isinstance(window_days, int)
        or not 1 <= window_days <= 365
    ):
        raise CampaignInputError(
            "window_days 必须是 1~365 之间的整数"
        )

    outcome = attribute_purchase(
        customer_id=customer_id,
        product_id=product_id,
        buy_date=buy_date,
        strategy_date=customer_strategy_date(customer_id),
        top3={customer_id: customer_top3(customer_id)},
        window_days=window_days,
    )
    if not outcome.matched or outcome.strategy_id is None:
        raise CampaignInputError(outcome.reason)

    if _existing_responded(outcome.strategy_id):
        raise CampaignInputError(
            f"策略 {outcome.strategy_id} 已有 responded 事件，"
            "重复购买只记首次，不重复归因"
        )

    row = _record_event(
        strategy_id=outcome.strategy_id,
        event_type="responded",
        occurred_at=occurred_at or datetime.now(),
        product_id=product_id,
        amount=amount,
    )
    return {**row, "attribution": outcome.reason, "rank": outcome.rank}


def simulate_holding_purchase(
    *,
    customer_id: str,
    product_id: str,
    buy_date: date,
    amount: float = 50_000.0,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """写入一笔演示新增持仓，并在同一事务中完成响应归因。

    原始 ODS/DWD 持仓保持只读；演示事实写入 app_demo_holding。只有已触达、
    位于归因窗口且命中 Top3 的购买才能生成 responded 事件，因此 KPI 仍由
    事件事实聚合，而不是由前端直接加数。
    """
    if not customer_id:
        raise CampaignInputError("customer_id 不能为空")
    if not product_id:
        raise CampaignInputError("product_id 不能为空")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise CampaignInputError("amount 必须是大于 0 的数字")
    if (
        isinstance(window_days, bool)
        or not isinstance(window_days, int)
        or not 1 <= window_days <= 365
    ):
        raise CampaignInputError("window_days 必须是 1~365 之间的整数")

    outcome = attribute_purchase(
        customer_id=customer_id,
        product_id=product_id,
        buy_date=buy_date,
        strategy_date=customer_strategy_date(customer_id),
        top3={customer_id: customer_top3(customer_id)},
        window_days=window_days,
    )
    if not outcome.matched or outcome.strategy_id is None:
        raise CampaignInputError(outcome.reason)

    holding_id = f"SIM{uuid4().hex.upper()}"
    occurred_at = datetime.combine(buy_date, time(hour=10))
    connection = None
    try:
        connection = database_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(event_type = 'sent'), 0) AS sent_count, "
                "COALESCE(SUM(event_type = 'responded'), 0) AS responded_count "
                "FROM app_campaign_event WHERE strategy_id = %s",
                (outcome.strategy_id,),
            )
            counts = cursor.fetchone() or {}
            if int(counts.get("sent_count", 0)) == 0:
                raise CampaignInputError(
                    f"策略 {outcome.strategy_id} 尚未触达，请先标记已触达"
                )
            if int(counts.get("responded_count", 0)) > 0:
                raise CampaignInputError(
                    f"策略 {outcome.strategy_id} 已有 responded 事件，"
                    "重复模拟不会再次增加 KPI"
                )

            cursor.execute(
                "INSERT INTO app_demo_holding "
                "(holding_id, customer_id, product_id, amount, buy_date, "
                "attributed_strategy_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    holding_id,
                    customer_id,
                    product_id,
                    amount,
                    buy_date,
                    outcome.strategy_id,
                ),
            )
            cursor.execute(
                "INSERT INTO app_campaign_event "
                "(strategy_id, event_type, occurred_at, product_id, amount) "
                "VALUES (%s, 'responded', %s, %s, %s)",
                (outcome.strategy_id, occurred_at, product_id, amount),
            )
            cursor.execute(
                "SELECT campaign_event_id, strategy_id, event_type, "
                "occurred_at, product_id, amount, created_at "
                "FROM app_campaign_event WHERE campaign_event_id = LAST_INSERT_ID()"
            )
            event = cursor.fetchone()
            cursor.execute(
                "SELECT holding_id, customer_id, product_id, amount, buy_date, "
                "attributed_strategy_id, created_at FROM app_demo_holding "
                "WHERE holding_id = %s",
                (holding_id,),
            )
            holding = cursor.fetchone()
        connection.commit()
    except CampaignInputError:
        if connection is not None:
            connection.rollback()
        raise
    except pymysql.IntegrityError as exc:
        if connection is not None:
            connection.rollback()
        if exc.args and exc.args[0] == 1062:
            raise CampaignInputError(
                f"策略 {outcome.strategy_id} 已完成响应归因，重复模拟不会再次增加 KPI"
            ) from exc
        raise CampaignStoreError("unable to simulate holding purchase") from exc
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        if connection is not None:
            connection.rollback()
        raise CampaignStoreError("unable to simulate holding purchase") from exc
    finally:
        if connection is not None:
            connection.close()

    if event is None or holding is None:
        raise CampaignStoreError("simulated holding purchase was not found")

    manager_delta = int(
        customer_strategy_channel(customer_id, int(outcome.rank)) == "manager"
    )
    return {
        "holding": _event_json(holding),
        "event": {
            **_event_json(event),
            "attribution": outcome.reason,
            "rank": outcome.rank,
        },
        "kpi_delta": {
            "responded": 1,
            "manager_conversion": manager_delta,
        },
        "demo": True,
    }


def list_campaign_events(
    customer_id: str | None = None,
    strategy_id: str | None = None,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> list[dict]:
    """查询事件（按客户或按策略过滤），按发生时间排序。"""
    conditions: list[str] = []
    params: list[object] = []
    conditions.append("occurred_at < %s")
    params.append(datetime.combine(business_date + timedelta(days=1), time.min))
    if customer_id:
        conditions.append(
            "strategy_id IN (%s, %s, %s)"
        )
        params.extend([f"{customer_id}:1", f"{customer_id}:2", f"{customer_id}:3"])
    if strategy_id:
        _parse_strategy_id(strategy_id)
        conditions.append("strategy_id = %s")
        params.append(strategy_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    statement = (
        "SELECT campaign_event_id, strategy_id, event_type, occurred_at, "
        f"product_id, amount, created_at FROM app_campaign_event {where} "
        "ORDER BY occurred_at, campaign_event_id"
    )
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, tuple(params))
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to list campaign events") from exc
    return [_event_json(row) for row in rows]


# ----------------------------------------------------------------
# 客户策略查询（Tab3 策略卡 + 批处理规则轨迹 + 执行状态）
# ----------------------------------------------------------------


def _customer_profile_and_products(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> tuple[dict, dict[str, dict]]:
    """从DWD读取展示字段；不在请求时重算规则或回读原始文件。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT customer_id, risk_appetite, vip_level, aum "
                    "FROM dwd_dim_customer WHERE customer_id=%s "
                    "AND register_date <= %s",
                    (customer_id, business_date),
                )
                customer = cursor.fetchone()
                cursor.execute(
                    "SELECT product_id, product_name, risk_level, "
                    "expected_return, product_type FROM dwd_dim_product"
                )
                products = {
                    str(row["product_id"]): row for row in cursor.fetchall()
                }
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query DWD strategy dimensions") from exc
    if customer is None:
        raise CampaignInputError(f"客户 {customer_id} 不存在")
    return customer, products


def _parse_rule_trace(value: Any) -> list[dict]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CampaignStoreError("ADS策略规则轨迹不是合法JSON") from exc
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise CampaignStoreError("ADS策略规则轨迹缺失")
    return [dict(item) for item in parsed]


def _derive_status(strategy_id: str, events: list[dict]) -> str:
    """状态按客户口径推导：触达一次即全客户策略进入已触达。

    响应仍按 strategy_id 归因（购买产品 ∈ Top3 命中对应 rank）。
    """
    customer_id = str(strategy_id).partition(":")[0]
    responded = any(
        event["event_type"] == "responded"
        and event["strategy_id"] == strategy_id
        for event in events
    )
    if responded:
        return "已响应"
    sent = any(
        event["event_type"] == "sent"
        and str(event["strategy_id"]).partition(":")[0] == customer_id
        for event in events
    )
    return "已触达" if sent else "待执行"


def _execution_script(marketing_script: str) -> tuple[str, bool]:
    """在执行出口补齐统一风险提示，不修改赛事提交文件。"""
    script = str(marketing_script).strip()
    if COMPLIANCE_NOTE in script:
        return script, False

    # 历史批次可能使用较短的旧版尾注。执行出口替换为统一文本，
    # 避免把两个近似风险提示连续展示给客户。
    for legacy_note in (
        "理财非存款、产品有风险。",
        "理财非存款，产品有风险。",
    ):
        if script.endswith(legacy_note):
            script = script[: -len(legacy_note)].rstrip()
            break

    separator = "" if script.endswith(("。", "！", "？", "!", "?")) else "。"
    budget = 300 - len(separator) - len(COMPLIANCE_NOTE)
    if len(script) > budget:
        script = f"{script[: max(budget - 1, 0)]}…"
    return f"{script}{separator}{COMPLIANCE_NOTE}", True


def customer_strategies(
    customer_id: str,
    business_date: date = DEFAULT_BUSINESS_DATE,
) -> dict:
    """返回ADS日批Top3、批处理时冻结的规则轨迹与执行状态。"""
    source_rows = _require_strategy_rows(customer_id, business_date)
    customer, products = _customer_profile_and_products(customer_id, business_date)
    as_of = customer_strategy_date(customer_id, business_date)
    events = list_campaign_events(
        customer_id=customer_id,
        business_date=business_date,
    )

    items: list[dict] = []
    for row in source_rows:
        strategy_id = str(row["strategy_id"])
        product_id = str(row["product_id"])
        product = products.get(product_id)
        if product is None:
            raise CampaignInputError(
                f"产品 {product_id} 不在产品池 P001~P030"
            )
        execution_script, script_adjusted = _execution_script(
            str(row["marketing_script"])
        )
        trace = _parse_rule_trace(row.get("rule_trace_json"))
        items.append(
            {
                "strategy_id": strategy_id,
                "rank": int(row["rank"]),
                "product_id": product_id,
                "product_name": product["product_name"],
                "risk_level": product["risk_level"],
                "expected_return": round(float(product["expected_return"]), 4),
                "product_type": product["product_type"],
                "recommended_channel": row["recommended_channel"],
                "recommended_time": row["recommended_time"],
                "marketing_script": execution_script,
                "script_adjusted": script_adjusted,
                "model_prob": _json_value(row.get("model_prob")),
                "a1_rank": int(row["a1_rank"]),
                "selection_reason": row["selection_reason"],
                "model_version": row["model_version"],
                "rule_version": row["rule_version"],
                "batch_id": row["batch_id"],
                "status": _derive_status(strategy_id, events),
                "execution_enabled": all(bool(outcome.get("passed")) for outcome in trace),
                "rule_trace": trace,
            }
        )
    return {
        "customer_id": customer_id,
        "strategy_date": as_of.isoformat(),
        "strategy_source": "warehouse_batch",
        "risk_appetite": customer["risk_appetite"],
        "vip_level": customer["vip_level"],
        "aum": round(float(customer["aum"]), 2),
        "batch_id": source_rows[0]["batch_id"],
        "model_version": source_rows[0]["model_version"],
        "rule_version": source_rows[0]["rule_version"],
        "items": items,
    }
