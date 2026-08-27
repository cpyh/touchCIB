"""A2 数据装载：CSV → 引擎数据结构（as-of 行为聚合 + A1 信号装载）。"""

from __future__ import annotations

from datetime import date
from typing import Mapping

import pandas as pd

from .models import Customer, CustomerBehavior, Product


def load_customers(path) -> dict[str, Customer]:
    frame = pd.read_csv(path, dtype={"customer_id": str})
    frame["register_date"] = pd.to_datetime(
        frame["register_date"], errors="raise"
    ).dt.normalize()
    return {
        row.customer_id: Customer(
            customer_id=row.customer_id,
            age_group=row.age_group,
            city=row.city,
            occupation=row.occupation,
            income_level=row.income_level,
            register_date=row.register_date.date(),
            aum=float(row.aum),
            risk_appetite=row.risk_appetite,
            vip_level=row.vip_level,
            has_app=bool(int(row.has_app)),
        )
        for row in frame.itertuples(index=False)
    }


def load_products(path) -> list[Product]:
    frame = pd.read_csv(path, dtype={"product_id": str})
    frame["launch_date"] = pd.to_datetime(
        frame["launch_date"], errors="raise"
    ).dt.normalize()
    products = [
        Product(
            product_id=row.product_id,
            product_name=row.product_name,
            product_type=row.product_type,
            risk_level=row.risk_level,
            expected_return=float(row.expected_return),
            volatility=float(row.volatility),
            min_invest=float(row.min_invest),
            duration_days=int(row.duration_days),
            liquidity=row.liquidity,
            launch_date=row.launch_date.date(),
        )
        for row in frame.itertuples(index=False)
    ]
    return sorted(products, key=lambda product: product.product_id)


def load_strategy_customers(path) -> dict[str, date]:
    """读取 partA_strategy_customers.csv，返回 customer_id -> strategy_date。"""
    frame = pd.read_csv(path, dtype={"customer_id": str})
    frame["strategy_date"] = pd.to_datetime(
        frame["strategy_date"], errors="raise"
    ).dt.normalize()
    if frame["customer_id"].duplicated().any():
        raise ValueError("partA_strategy_customers.csv 存在重复 customer_id")
    return {
        row.customer_id: row.strategy_date.date()
        for row in frame.itertuples(index=False)
    }


def build_behaviors(
    customers: Mapping[str, Customer],
    events: pd.DataFrame,
    holdings: pd.DataFrame,
    strategy_dates: Mapping[str, date],
) -> dict[str, CustomerBehavior]:
    """按 strategy_date 做 as-of 截断，聚合每个客户的持仓与行为事件。

    窗口口径（严格早于策略日）：
    - complaint/consult：0 < 距策略日天数 ≤ 90
    - login：0 < 距策略日天数 ≤ 30
    - 持仓：buy_date < strategy_date
    """
    dates = pd.DataFrame(
        {
            "customer_id": list(strategy_dates),
            "strategy_date": [pd.Timestamp(d) for d in strategy_dates.values()],
        }
    )
    events["event_date"] = pd.to_datetime(
        events["event_date"], errors="raise"
    ).dt.normalize()
    holdings["buy_date"] = pd.to_datetime(
        holdings["buy_date"], errors="raise"
    ).dt.normalize()

    event_links = dates.merge(
        events[["customer_id", "event_type", "event_date"]],
        on="customer_id",
        how="left",
    )
    event_links["days_before"] = (
        event_links["strategy_date"] - event_links["event_date"]
    ).dt.days
    valid_events = event_links[event_links["days_before"] > 0]
    complaint = (
        valid_events[
            (valid_events["event_type"] == "complaint")
            & (valid_events["days_before"] <= 90)
        ]
        .groupby("customer_id", sort=False)
        .size()
    )
    consult = (
        valid_events[
            (valid_events["event_type"] == "consult")
            & (valid_events["days_before"] <= 90)
        ]
        .groupby("customer_id", sort=False)
        .size()
    )
    login = (
        valid_events[
            (valid_events["event_type"] == "login")
            & (valid_events["days_before"] <= 30)
        ]
        .groupby("customer_id", sort=False)
        .size()
    )

    holding_links = dates.merge(
        holdings[["customer_id", "product_id", "buy_date"]],
        on="customer_id",
        how="left",
    )
    valid_holdings = holding_links[
        holding_links["buy_date"].notna()
        & (holding_links["buy_date"] < holding_links["strategy_date"])
    ]
    held_products = (
        valid_holdings.groupby("customer_id", sort=False)["product_id"]
        .apply(lambda series: tuple(sorted(set(series))))
    )

    behaviors: dict[str, CustomerBehavior] = {}
    for customer_id in strategy_dates:
        behaviors[customer_id] = CustomerBehavior(
            customer_id=customer_id,
            holding_product_ids=tuple(held_products.get(customer_id, ())),
            complaint_count_90d=int(complaint.get(customer_id, 0)),
            consult_count_90d=int(consult.get(customer_id, 0)),
            login_count_30d=int(login.get(customer_id, 0)),
        )
    return behaviors
