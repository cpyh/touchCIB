"""A1 在线特征的数据源适配器。

离线训练继续使用官方 CSV，平台在线推理读取 MySQL DWD。两种数据源都返回
同构 DataFrame，使特征工程和模型代码保持唯一实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import pandas as pd

from ..database import database_connection
from . import config


@dataclass(frozen=True)
class A1DataBundle:
    customers: pd.DataFrame
    products: pd.DataFrame
    campaigns: pd.DataFrame
    holdings: pd.DataFrame
    events: pd.DataFrame


class A1DataSource(Protocol):
    def load(self, *, history_cutoff: str | None = None) -> A1DataBundle: ...


DATE_COLUMNS = {
    "customers": ("register_date",),
    "products": ("launch_date",),
    "campaigns": ("contact_date",),
    "holdings": ("buy_date",),
    "events": ("event_date",),
}

NUMERIC_COLUMNS = {
    "customers": ("aum", "has_app"),
    "products": (
        "expected_return",
        "volatility",
        "min_invest",
        "duration_days",
    ),
    "campaigns": ("responded",),
    "holdings": ("amount",),
    "events": (),
}


def _normalize(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    """把 CSV/PyMySQL 的 date、Decimal 等差异收敛成模型所需 dtype。"""
    if frame.empty:
        raise RuntimeError(f"A1 data source returned an empty {name} table")
    result = frame.copy()
    for column in DATE_COLUMNS[name]:
        result[column] = pd.to_datetime(result[column], errors="raise").dt.normalize()
    for column in NUMERIC_COLUMNS[name]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    if "has_app" in result:
        result["has_app"] = result["has_app"].astype(int)
    if "responded" in result:
        result["responded"] = result["responded"].astype(int)
    if "duration_days" in result:
        result["duration_days"] = result["duration_days"].astype(int)
    return result


class CsvDataSource:
    """官方 CSV 数据源，用于训练、回放和无数据库复现。"""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or config.DATA_DIR)

    def load(self, *, history_cutoff: str | None = None) -> A1DataBundle:
        data_dir = self.data_dir
        frames = {
            "customers": pd.read_csv(data_dir / "t_customer.csv"),
            "products": pd.read_csv(data_dir / "t_product.csv"),
            "campaigns": pd.read_csv(data_dir / "t_campaign.csv"),
            "holdings": pd.read_csv(data_dir / "t_holding.csv"),
            "events": pd.read_csv(data_dir / "t_event.csv"),
        }
        normalized = {name: _normalize(name, frame) for name, frame in frames.items()}
        if history_cutoff is not None:
            cutoff = pd.Timestamp(history_cutoff)
            normalized["campaigns"] = normalized["campaigns"].loc[
                normalized["campaigns"]["contact_date"] < cutoff
            ].reset_index(drop=True)
        return A1DataBundle(**normalized)


class MySQLDataSource:
    """DWD 数据源。一次连接读取五张小表，供进程内历史索引重复使用。"""

    QUERIES = {
        "customers": (
            "SELECT customer_id, age_group, city, occupation, income_level, "
            "register_date, aum, risk_appetite, vip_level, has_app "
            "FROM dwd_dim_customer"
        ),
        "products": (
            "SELECT product_id, product_name, product_type, risk_level, "
            "expected_return, volatility, min_invest, duration_days, liquidity, "
            "launch_date FROM dwd_dim_product"
        ),
        "holdings": (
            "SELECT holding_id, customer_id, product_id, amount, buy_date "
            "FROM dwd_fact_holding"
        ),
        "events": (
            "SELECT event_id, customer_id, event_type, event_date "
            "FROM dwd_fact_event"
        ),
    }

    def __init__(self, connection_factory: Callable = database_connection) -> None:
        self.connection_factory = connection_factory

    def load(self, *, history_cutoff: str | None = None) -> A1DataBundle:
        connection = self.connection_factory()
        try:
            frames: dict[str, pd.DataFrame] = {}
            with connection.cursor() as cursor:
                for name, query in self.QUERIES.items():
                    cursor.execute(query)
                    frames[name] = pd.DataFrame(cursor.fetchall())

                campaign_query = (
                    "SELECT contact_id, customer_id, product_id, channel, "
                    "contact_date, responded FROM dwd_fact_campaign"
                )
                params: tuple[object, ...] = ()
                if history_cutoff is not None:
                    campaign_query += " WHERE contact_date < %s"
                    params = (history_cutoff,)
                cursor.execute(campaign_query, params)
                frames["campaigns"] = pd.DataFrame(cursor.fetchall())
        finally:
            connection.close()

        normalized = {name: _normalize(name, frame) for name, frame in frames.items()}
        return A1DataBundle(**normalized)


__all__ = [
    "A1DataBundle",
    "A1DataSource",
    "CsvDataSource",
    "MySQLDataSource",
]
