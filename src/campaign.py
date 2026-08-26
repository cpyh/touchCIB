"""营销触达事件服务：埋点写入（含归因校验）、事件查询与状态推导。

事件模型（docs/demo-design.md §2）：
- append-only，永不 UPDATE/DELETE；
- sent 事件：运营标记"已触达"；
- responded 事件：购买事实经归因规则校验后写入；
- "待执行"不存储——策略存在且无任何事件即推导得出。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import pymysql

from .database import database_connection
from .marketing.attribution import DEFAULT_WINDOW_DAYS, attribute_purchase
from .marketing.templates import COMPLIANCE_NOTE

PROJECT_DIR = Path(__file__).resolve().parents[1]
STRATEGY_CSV = PROJECT_DIR / "partA_strategy.csv"
STRATEGY_CUSTOMERS_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_strategy_customers.csv"
)
CUSTOMER_CSV = PROJECT_DIR / "src" / "data" / "raw" / "t_customer.csv"

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


@lru_cache(maxsize=1)
def load_strategy_frame() -> pd.DataFrame:
    frame = pd.read_csv(STRATEGY_CSV, dtype=str)
    expected = [
        "customer_id",
        "rank",
        "product_id",
        "recommended_channel",
        "recommended_time",
        "marketing_script",
    ]
    if list(frame.columns) != expected:
        raise CampaignStoreError(
            f"策略文件列名不符：{list(frame.columns)}"
        )
    return frame


@lru_cache(maxsize=1)
def strategy_top3() -> dict[str, tuple[str, str, str]]:
    """customer_id -> (rank1, rank2, rank3) 产品元组。"""
    frame = load_strategy_frame()
    official_ids = set(_official_strategy_dates())
    submitted_ids = set(frame["customer_id"])
    if submitted_ids != official_ids:
        missing = sorted(official_ids - submitted_ids)[:3]
        extra = sorted(submitted_ids - official_ids)[:3]
        raise CampaignStoreError(
            f"正式策略客户与A2目标名单不一致：missing={missing}, extra={extra}"
        )
    result: dict[str, tuple[str, str, str]] = {}
    for customer_id, group in frame.groupby("customer_id", sort=False):
        ranks = group["rank"].tolist()
        ordered = group.sort_values("rank")["product_id"].tolist()
        if len(group) != 3 or set(ranks) != {"1", "2", "3"}:
            raise CampaignStoreError(
                f"A2客户 {customer_id} 的正式策略必须恰好包含rank 1/2/3"
            )
        if len(set(ordered)) != 3:
            raise CampaignStoreError(
                f"A2客户 {customer_id} 的正式Top3产品不得重复"
            )
        result[customer_id] = tuple(ordered)
    return result


@lru_cache(maxsize=1)
def strategy_date() -> date:
    frame = pd.read_csv(
        STRATEGY_CUSTOMERS_CSV, dtype={"customer_id": str}
    )
    dates = pd.to_datetime(frame["strategy_date"], errors="raise").dt.date
    return max(dates)


@lru_cache(maxsize=1)
def _official_strategy_dates() -> dict[str, date]:
    frame = pd.read_csv(
        STRATEGY_CUSTOMERS_CSV, dtype={"customer_id": str}
    )
    frame["strategy_date"] = pd.to_datetime(
        frame["strategy_date"], errors="raise"
    ).dt.date
    return dict(zip(frame["customer_id"], frame["strategy_date"], strict=True))


@lru_cache(maxsize=1)
def _known_customer_ids() -> frozenset[str]:
    frame = pd.read_csv(CUSTOMER_CSV, dtype={"customer_id": str})
    return frozenset(frame["customer_id"])


@lru_cache(maxsize=512)
def _live_strategy_payload(customer_id: str) -> dict:
    """为非A2客户稳定生成Top3；进程内缓存避免重复在线打分。"""
    if customer_id not in _known_customer_ids():
        raise CampaignInputError(f"客户 {customer_id} 不存在")
    try:
        from .marketing.generate import generate_customer_strategy
        from .partA1serving.runtime import get_mysql_predictor

        return generate_customer_strategy(
            customer_id,
            response_predictor=get_mysql_predictor(),
        )
    except CampaignInputError:
        raise
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise CampaignStoreError("unable to generate live customer strategy") from exc


def _stored_live_strategy_rows(customer_id: str) -> list[dict]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT strategy_id, customer_id, strategy_rank AS `rank`, strategy_date, "
                    "product_id, recommended_channel, recommended_time, "
                    "marketing_script, score, model_prob, cf_score, overshoot, "
                    "created_at FROM app_marketing_strategy "
                    "WHERE customer_id = %s ORDER BY strategy_rank",
                    (customer_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise CampaignStoreError("unable to query live strategy snapshot") from exc
    return list(rows)


def _ensure_live_strategy_rows(customer_id: str) -> list[dict]:
    """首次生成后冻结非A2客户Top3，确保后续事件与归因不会漂移。"""
    if customer_id in _official_strategy_dates():
        raise CampaignStoreError(f"A2客户 {customer_id} 禁止写入运行策略快照")
    rows = _stored_live_strategy_rows(customer_id)
    if rows:
        if len(rows) != 3:
            raise CampaignStoreError(
                f"客户 {customer_id} 的运行策略快照不完整：{len(rows)}/3"
            )
        return rows

    payload = _live_strategy_payload(customer_id)
    items = payload.get("items", [])
    ranks = {int(item["rank"]) for item in items}
    products = [str(item["product_id"]) for item in items]
    if len(items) != 3 or ranks != {1, 2, 3}:
        raise CampaignStoreError(f"客户 {customer_id} 实时策略必须恰好包含rank 1/2/3")
    if len(set(products)) != 3:
        raise CampaignStoreError(f"客户 {customer_id} 实时Top3产品不得重复")
    values = [
        (
            f"{customer_id}:{int(item['rank'])}",
            customer_id,
            int(item["rank"]),
            payload["strategy_date"],
            item["product_id"],
            item["recommended_channel"],
            item["recommended_time"],
            item["marketing_script"],
            item["score"],
            item["model_prob"],
            item["cf_score"],
            int(bool(item.get("overshoot", False))),
        )
        for item in items
    ]

    connection = None
    try:
        connection = database_connection()
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO app_marketing_strategy "
                "(strategy_id, customer_id, strategy_rank, strategy_date, product_id, "
                "recommended_channel, recommended_time, marketing_script, "
                "score, model_prob, cf_score, overshoot) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                values,
            )
        connection.commit()
    except pymysql.IntegrityError as exc:
        if connection is not None:
            connection.rollback()
        if not exc.args or exc.args[0] != 1062:
            raise CampaignStoreError("unable to freeze live strategy snapshot") from exc
        # 并发请求可能已经完成同一客户的首次冻结；回读获胜快照。
        rows = _stored_live_strategy_rows(customer_id)
        if len(rows) == 3:
            return rows
        raise CampaignStoreError("concurrent live strategy snapshot is incomplete")
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        if connection is not None:
            connection.rollback()
        raise CampaignStoreError("unable to freeze live strategy snapshot") from exc
    finally:
        if connection is not None:
            connection.close()

    rows = _stored_live_strategy_rows(customer_id)
    if len(rows) != 3:
        raise CampaignStoreError("frozen live strategy snapshot was not found")
    return rows


def customer_strategy_date(customer_id: str) -> date:
    """官方客户使用输入日期，其他客户使用当前活动统一日期。"""
    if customer_id not in _known_customer_ids():
        raise CampaignInputError(f"客户 {customer_id} 不存在")
    official = _official_strategy_dates().get(customer_id)
    if official is not None:
        return official
    rows = _ensure_live_strategy_rows(customer_id)
    value = rows[0]["strategy_date"]
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def customer_top3(customer_id: str) -> tuple[str, str, str]:
    """取得客户当前Top3：A2读取提交版，其他客户按需实时生成。"""
    if customer_id in _official_strategy_dates():
        official = strategy_top3().get(customer_id)
        if official is None:
            raise CampaignStoreError(f"A2客户 {customer_id} 缺少正式Top3")
        return official
    rows = _ensure_live_strategy_rows(customer_id)
    products = tuple(row["product_id"] for row in rows)
    if len(products) != 3:
        raise CampaignStoreError(f"客户 {customer_id} 实时策略没有恰好3个产品")
    return products


def customer_strategy_channel(customer_id: str, rank: int) -> str:
    """取得某条策略的执行渠道，供KPI与演示归因共用。"""
    if customer_id in _official_strategy_dates():
        strategy_top3()  # 先验证提交版与A2名单及Top3完整性。
        official = load_strategy_frame()
        rows = official[
            (official["customer_id"] == customer_id)
            & (official["rank"] == str(rank))
        ]
        if rows.empty:
            raise CampaignStoreError(f"A2策略不存在：{customer_id}:{rank}")
        return str(rows.iloc[0]["recommended_channel"])
    for item in _ensure_live_strategy_rows(customer_id):
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
    # 非A2客户会在首次执行前按需生成并缓存Top3；由此保证rank确实存在。
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
    """标记"已触达"：写入 sent 事件。"""
    _parse_strategy_id(strategy_id)
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
) -> list[dict]:
    """查询事件（按客户或按策略过滤），按发生时间排序。"""
    conditions: list[str] = []
    params: list[str] = []
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
# 客户策略查询（Tab3 策略卡 + 规则轨迹 + 执行状态）
# ----------------------------------------------------------------

# 对外部提交行（队友生成）只做"校验型"规则轨迹；manager 配额等生成期规则不适用
TRACE_RULE_IDS = (
    "risk_match",
    "product_launched",
    "customer_registered",
    "duration_valid",
    "channel_app_requires_app",
    "channel_call_complaint_block",
    "slot_in_enum",
    "script_length",
    "script_compliance_note",
)


@lru_cache(maxsize=1)
def _trace_context():
    """装载轨迹求值所需上下文（客户/产品/行为/引擎/策略日期）。"""
    from .marketing.io import (
        build_behaviors,
        load_customers,
        load_products,
    )
    from .marketing.rules import build_default_engine
    from .marketing.models import RISK_RANK

    raw = PROJECT_DIR / "src" / "data" / "raw"
    customers = load_customers(raw / "t_customer.csv")
    products = {p.product_id: p for p in load_products(raw / "t_product.csv")}
    events = pd.read_csv(raw / "t_event.csv", dtype={"customer_id": str})
    holdings = pd.read_csv(
        raw / "t_holding.csv",
        dtype={"customer_id": str, "product_id": str},
    )
    strategy_dates_frame = pd.read_csv(
        STRATEGY_CUSTOMERS_CSV, dtype={"customer_id": str}
    )
    strategy_dates = {
        row.customer_id: pd.to_datetime(row.strategy_date).date()
        for row in strategy_dates_frame.itertuples()
    }
    activity_date = max(strategy_dates.values())
    strategy_dates = {
        customer_id: strategy_dates.get(customer_id, activity_date)
        for customer_id in customers
    }
    behaviors = build_behaviors(customers, events, holdings, strategy_dates)
    engine = build_default_engine()
    return customers, products, behaviors, engine, strategy_dates, RISK_RANK


def _derive_status(strategy_id: str, events: list[dict]) -> str:
    responded = any(
        event["event_type"] == "responded"
        and event["strategy_id"] == strategy_id
        for event in events
    )
    if responded:
        return "已响应"
    sent = any(
        event["event_type"] == "sent" and event["strategy_id"] == strategy_id
        for event in events
    )
    return "已触达" if sent else "待执行"


def _execution_script(marketing_script: str) -> tuple[str, bool]:
    """在执行出口补齐统一风险提示，不修改赛事提交文件。"""
    script = str(marketing_script).strip()
    if COMPLIANCE_NOTE in script:
        return script, False

    # 队友提交文件使用了较短的旧版尾注。执行出口替换为统一文本，
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


def customer_strategies(customer_id: str) -> dict:
    """返回某客户 Top3 策略卡数据：策略行 + 规则轨迹 + 事件状态。

    A2客户读取正式提交版；其他客户首次访问时生成并冻结运行快照。
    未触达不存储事件——无事件即推导为"待执行"。
    """
    frame = load_strategy_frame()
    customers, products, behaviors, engine, strategy_dates, risk_rank = (
        _trace_context()
    )
    if customer_id not in customers:
        raise CampaignInputError(f"客户 {customer_id} 不存在")

    official_target = customer_id in _official_strategy_dates()
    official_rows = frame[frame["customer_id"] == customer_id].sort_values("rank")
    if official_target:
        strategy_top3()  # fail fast：A2客户必须完整存在于正式提交版。
        source_rows = [
            {
                "strategy_id": f"{row.customer_id}:{row.rank}",
                "rank": int(row.rank),
                "product_id": row.product_id,
                "recommended_channel": row.recommended_channel,
                "recommended_time": row.recommended_time,
                "marketing_script": row.marketing_script,
                "score": None,
                "model_prob": None,
                "cf_score": None,
                "overshoot": False,
            }
            for row in official_rows.itertuples()
        ]
    else:
        source_rows = _ensure_live_strategy_rows(customer_id)

    customer = customers[customer_id]
    behavior = behaviors[customer_id]
    as_of = customer_strategy_date(customer_id)
    events = list_campaign_events(customer_id=customer_id)

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
        context = {
            "customer": customer,
            "behavior": behavior,
            "product": product,
            "strategy_date": as_of,
            "channel": row["recommended_channel"],
            "recommended_time": row["recommended_time"],
            "marketing_script": execution_script,
            "max_allowed_risk": risk_rank[customer.risk_appetite] + 1,
            "overshoot": bool(row.get("overshoot", False)),
        }
        trace = [
            outcome
            for outcome in engine.evaluate_all(context)
            if outcome.rule_id in TRACE_RULE_IDS
        ]
        items.append(
            {
                "strategy_id": strategy_id,
                "rank": int(row["rank"]),
                "product_id": product_id,
                "product_name": product.product_name,
                "risk_level": product.risk_level,
                "expected_return": round(float(product.expected_return), 4),
                "product_type": product.product_type,
                "recommended_channel": row["recommended_channel"],
                "recommended_time": row["recommended_time"],
                "marketing_script": execution_script,
                "script_adjusted": script_adjusted,
                "score": _json_value(row.get("score")),
                "model_prob": _json_value(row.get("model_prob")),
                "cf_score": _json_value(row.get("cf_score")),
                "status": _derive_status(strategy_id, events),
                "execution_enabled": all(outcome.passed for outcome in trace),
                "rule_trace": [
                    {
                        "rule_id": outcome.rule_id,
                        "passed": outcome.passed,
                        "reason": outcome.reason,
                    }
                    for outcome in trace
                ],
            }
        )
    return {
        "customer_id": customer_id,
        "strategy_date": as_of.isoformat(),
        "official_target": official_target,
        "strategy_source": (
            "official_submission" if official_target else "live_generated"
        ),
        "risk_appetite": customer.risk_appetite,
        "vip_level": customer.vip_level,
        "aum": round(float(customer.aum), 2),
        "items": items,
    }
