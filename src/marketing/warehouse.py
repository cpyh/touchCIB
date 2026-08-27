"""营销业务的数据仓库适配层。

Flask、批处理和规则引擎只通过本模块读取 DWD/ADS。CSV 只保留给初始 ODS
装载、离线训练和最终提交导出，不再作为线上业务数据源。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from ..partA1serving.data_source import A1DataSource, MySQLDataSource
from .io import build_behaviors
from .models import Customer, CustomerBehavior, Product


@dataclass(frozen=True)
class MarketingWarehouseContext:
    customers: dict[str, Customer]
    products: tuple[Product, ...]
    behaviors: dict[str, CustomerBehavior]
    strategy_date: date


def _customers(frame: pd.DataFrame) -> dict[str, Customer]:
    return {
        str(row.customer_id): Customer(
            customer_id=str(row.customer_id),
            age_group=str(row.age_group),
            city=str(row.city),
            occupation=str(row.occupation),
            income_level=str(row.income_level),
            register_date=pd.Timestamp(row.register_date).date(),
            aum=float(row.aum),
            risk_appetite=str(row.risk_appetite),
            vip_level=str(row.vip_level),
            has_app=bool(int(row.has_app)),
        )
        for row in frame.itertuples(index=False)
    }


def _products(frame: pd.DataFrame) -> tuple[Product, ...]:
    items = [
        Product(
            product_id=str(row.product_id),
            product_name=str(row.product_name),
            product_type=str(row.product_type),
            risk_level=str(row.risk_level),
            expected_return=float(row.expected_return),
            volatility=float(row.volatility),
            min_invest=float(row.min_invest),
            duration_days=int(row.duration_days),
            liquidity=str(row.liquidity),
            launch_date=pd.Timestamp(row.launch_date).date(),
        )
        for row in frame.itertuples(index=False)
    ]
    return tuple(sorted(items, key=lambda item: item.product_id))


def load_marketing_context(
    strategy_date: date,
    *,
    customer_ids: Iterable[str] | None = None,
    data_source: A1DataSource | None = None,
) -> MarketingWarehouseContext:
    """从 DWD 装载批处理上下文，并严格按 strategy_date 聚合行为。"""
    bundle = (data_source or MySQLDataSource()).load()
    all_customers = _customers(bundle.customers)
    if customer_ids is not None:
        requested = tuple(dict.fromkeys(str(value) for value in customer_ids))
        missing = [
            customer_id for customer_id in requested if customer_id not in all_customers
        ]
        if missing:
            raise ValueError(f"客户不存在：{', '.join(missing[:3])}")
        not_registered = [
            customer_id
            for customer_id in requested
            if all_customers[customer_id].register_date > strategy_date
        ]
        if not_registered:
            raise ValueError(
                f"客户在策略日尚未注册：{', '.join(not_registered[:3])}"
            )
        customers = {
            customer_id: all_customers[customer_id] for customer_id in requested
        }
    else:
        customers = {
            customer_id: customer
            for customer_id, customer in all_customers.items()
            if customer.register_date <= strategy_date
        }

    strategy_dates = {customer_id: strategy_date for customer_id in customers}
    behaviors = build_behaviors(
        customers,
        bundle.events.copy(),
        bundle.holdings.copy(),
        strategy_dates,
    )
    return MarketingWarehouseContext(
        customers=customers,
        products=_products(bundle.products),
        behaviors=behaviors,
        strategy_date=strategy_date,
    )


__all__ = ["MarketingWarehouseContext", "load_marketing_context"]
