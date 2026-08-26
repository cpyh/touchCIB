"""客户经理营销机会队列：全量8000客户，A2名单仅作为赛事目标标识。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import pymysql

from ..database import database_connection

PROJECT_DIR = Path(__file__).resolve().parents[2]
STRATEGY_CSV = PROJECT_DIR / "partA_strategy.csv"
PREDICTION_CSV = PROJECT_DIR / "partA_prediction.csv"
RAW_DIR = PROJECT_DIR / "src" / "data" / "raw"
STATUS_VALUES = ("all", "pending", "follow_up", "converted")


class MarketingTaskStoreError(RuntimeError):
    """营销任务数据不可用。"""


@lru_cache(maxsize=1)
def _task_frame() -> pd.DataFrame:
    """构造8000位客户的静态机会底表。"""
    strategies = pd.read_csv(
        STRATEGY_CSV,
        dtype={"customer_id": str, "product_id": str, "rank": int},
    )
    rank1 = strategies[strategies["rank"] == 1].copy()
    if len(rank1) != 2_000 or rank1["customer_id"].nunique() != 2_000:
        raise MarketingTaskStoreError("A2策略客户必须恰好为2000位")
    official_customers = pd.read_csv(
        RAW_DIR / "partA_strategy_customers.csv",
        dtype={"customer_id": str},
    )["customer_id"]
    if (
        len(official_customers) != 2_000
        or official_customers.nunique() != 2_000
        or set(rank1["customer_id"]) != set(official_customers)
    ):
        raise MarketingTaskStoreError("A2正式策略与官方目标客户名单不一致")

    customers = pd.read_csv(
        RAW_DIR / "t_customer.csv",
        dtype={"customer_id": str},
    )[["customer_id", "risk_appetite", "vip_level", "aum"]]
    if len(customers) != 8_000 or customers["customer_id"].nunique() != 8_000:
        raise MarketingTaskStoreError("全量客户表必须恰好为8000位")
    products = pd.read_csv(
        RAW_DIR / "t_product.csv",
        dtype={"product_id": str},
    )[["product_id", "product_name", "risk_level", "expected_return"]]

    contacts = pd.read_csv(
        RAW_DIR / "partA_test_contacts.csv",
        dtype={"contact_id": str, "customer_id": str, "product_id": str},
    )
    predictions = pd.read_csv(PREDICTION_CSV, dtype={"contact_id": str})
    opportunities = contacts.merge(predictions, on="contact_id", how="left")
    opportunities["response_prob"] = pd.to_numeric(
        opportunities["response_prob"], errors="coerce"
    )
    opportunities = (
        opportunities.sort_values(
            ["response_prob", "contact_id"], ascending=[False, True]
        )
        .drop_duplicates("customer_id")
        [[
            "customer_id",
            "contact_id",
            "product_id",
            "channel",
            "contact_date",
            "response_prob",
        ]]
        .rename(
            columns={
                "contact_id": "model_contact_id",
                "product_id": "opportunity_product_id",
                "channel": "opportunity_channel",
                "contact_date": "opportunity_date",
            }
        )
    )
    opportunity_products = products[["product_id", "product_name"]].rename(
        columns={
            "product_id": "opportunity_product_id",
            "product_name": "opportunity_product_name",
        }
    )
    opportunities = opportunities.merge(
        opportunity_products,
        on="opportunity_product_id",
        how="left",
    )

    frame = (
        customers.merge(rank1, on="customer_id", how="left")
        .merge(products, on="product_id", how="left")
        .merge(opportunities, on="customer_id", how="left")
    )
    frame["official_target"] = frame["rank"].notna()
    return frame


def _event_statuses() -> dict[str, str]:
    """从 append-only 事件推导客户级任务状态。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT SUBSTRING_INDEX(strategy_id, ':', 1) AS customer_id, "
                    "MAX(event_type = 'sent') AS has_sent, "
                    "MAX(event_type = 'responded') AS has_responded "
                    "FROM app_campaign_event GROUP BY customer_id"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise MarketingTaskStoreError("unable to query marketing task status") from exc

    statuses: dict[str, str] = {}
    for row in rows:
        if int(row["has_responded"] or 0):
            status = "converted"
        elif int(row["has_sent"] or 0):
            status = "follow_up"
        else:
            status = "pending"
        statuses[str(row["customer_id"])] = status
    return statuses


def _live_strategy_customers() -> frozenset[str]:
    """返回已冻结完整实时Top3的非A2客户。"""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT customer_id FROM app_marketing_strategy "
                    "GROUP BY customer_id HAVING COUNT(*) = 3"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise MarketingTaskStoreError("unable to query live strategy status") from exc
    return frozenset(str(row["customer_id"]) for row in rows)


def query_marketing_tasks(
    *,
    page: int = 1,
    size: int = 20,
    status: str = "all",
    keyword: str | None = None,
) -> dict:
    """分页返回全量客户机会；未产生事件的客户默认为待联系。"""
    if page < 1 or size < 1 or size > 100:
        raise ValueError("page >= 1, 1 <= size <= 100")
    if status not in STATUS_VALUES:
        raise ValueError(f"status must be one of {STATUS_VALUES}")

    frame = _task_frame().copy()
    statuses = _event_statuses()
    live_strategy_customers = _live_strategy_customers()
    frame["status"] = frame["customer_id"].map(statuses).fillna("pending")
    counts = {
        key: int((frame["status"] == key).sum())
        for key in STATUS_VALUES
        if key != "all"
    }
    counts["all"] = int(len(frame))

    if status != "all":
        frame = frame[frame["status"] == status]
    if keyword:
        term = keyword.strip().lower()
        if term:
            frame = frame[
                frame["customer_id"].str.lower().str.contains(term, na=False, regex=False)
                | frame["product_id"].fillna("").str.lower().str.contains(term, regex=False)
                | frame["product_name"].fillna("").str.lower().str.contains(term, regex=False)
                | frame["opportunity_product_id"].fillna("").str.lower().str.contains(term, regex=False)
                | frame["opportunity_product_name"].fillna("").str.lower().str.contains(term, regex=False)
            ]

    frame = frame.sort_values(
        ["response_prob", "official_target", "customer_id"],
        ascending=[False, False, True],
        na_position="last",
    )
    total = int(len(frame))
    start = (page - 1) * size
    rows = frame.iloc[start : start + size]

    tasks = []
    for row in rows.itertuples():
        probability = None if pd.isna(row.response_prob) else float(row.response_prob)
        official_target = bool(row.official_target)
        strategy_ready = official_target or row.customer_id in live_strategy_customers
        tasks.append(
            {
                "customer_id": row.customer_id,
                "risk_appetite": row.risk_appetite,
                "vip_level": row.vip_level,
                "aum": round(float(row.aum), 2),
                "status": row.status,
                "strategy_id": (
                    f"{row.customer_id}:1" if strategy_ready else None
                ),
                "official_target": official_target,
                "strategy_ready": strategy_ready,
                "strategy_source": (
                    "official_submission"
                    if official_target
                    else "live_generated"
                    if strategy_ready
                    else "live_on_demand"
                ),
                "product_id": None if pd.isna(row.product_id) else row.product_id,
                "product_name": None if pd.isna(row.product_name) else row.product_name,
                "risk_level": None if pd.isna(row.risk_level) else row.risk_level,
                "expected_return": (
                    None
                    if pd.isna(row.expected_return)
                    else round(float(row.expected_return), 6)
                ),
                "recommended_channel": (
                    None
                    if pd.isna(row.recommended_channel)
                    else row.recommended_channel
                ),
                "recommended_time": (
                    None
                    if pd.isna(row.recommended_time)
                    else row.recommended_time
                ),
                "response_prob": (
                    round(probability, 12) if probability is not None else None
                ),
                "opportunity_score": (
                    round(probability, 12) if probability is not None else None
                ),
                "opportunity_source": (
                    "a1_contact" if probability is not None else "not_in_a1_contacts"
                ),
                "model_contact_id": (
                    None if pd.isna(row.model_contact_id) else row.model_contact_id
                ),
                "opportunity_product_id": (
                    None
                    if pd.isna(row.opportunity_product_id)
                    else row.opportunity_product_id
                ),
                "opportunity_product_name": (
                    None
                    if pd.isna(row.opportunity_product_name)
                    else row.opportunity_product_name
                ),
                "opportunity_channel": (
                    None
                    if pd.isna(row.opportunity_channel)
                    else row.opportunity_channel
                ),
                "opportunity_date": (
                    None if pd.isna(row.opportunity_date) else row.opportunity_date
                ),
            }
        )

    return {
        "total": total,
        "population_total": int(len(_task_frame())),
        "page": page,
        "size": size,
        "counts": counts,
        "official_target_customers": int(_task_frame()["official_target"].sum()),
        "model_covered_customers": int(_task_frame()["response_prob"].notna().sum()),
        "unscored_customers": int(_task_frame()["response_prob"].isna().sum()),
        "coverage_rate": round(
            float(_task_frame()["response_prob"].notna().mean()), 6
        ),
        "tasks": tasks,
    }
