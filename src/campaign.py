"""营销触达事件服务：埋点写入（含归因校验）、事件查询与状态推导。

事件模型（docs/demo-design.md §2）：
- append-only，永不 UPDATE/DELETE；
- sent 事件：运营标记"已触达"；
- responded 事件：购买事实经归因规则校验后写入；
- "待执行"不存储——策略存在且无任何事件即推导得出。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import pymysql

from .database import database_connection
from .marketing.attribution import DEFAULT_WINDOW_DAYS, attribute_purchase

PROJECT_DIR = Path(__file__).resolve().parents[1]
STRATEGY_CSV = PROJECT_DIR / "partA_strategy.csv"
STRATEGY_CUSTOMERS_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_strategy_customers.csv"
)

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
    result: dict[str, tuple[str, str, str]] = {}
    for customer_id, group in frame.groupby("customer_id", sort=False):
        ordered = (
            group.sort_values("rank")["product_id"].tolist()
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


def _parse_strategy_id(strategy_id: str) -> tuple[str, int]:
    match = STRATEGY_ID_PATTERN.fullmatch(strategy_id or "")
    if not match:
        raise CampaignInputError(
            f"strategy_id 格式须为 {{customer_id}}:{{rank}}（rank 1-3），收到 {strategy_id!r}"
        )
    customer_id = match.group("customer_id")
    rank = int(match.group("rank"))
    if customer_id not in strategy_top3():
        raise CampaignInputError(
            f"策略不存在：{strategy_id}（客户不在目标名单或行缺失）"
        )
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

    outcome = attribute_purchase(
        customer_id=customer_id,
        product_id=product_id,
        buy_date=buy_date,
        strategy_date=strategy_date(),
        top3=strategy_top3(),
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
