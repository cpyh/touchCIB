"""A1 响应名单查询（Tab3 名单区块，前端零计算）。

数据源：src/data/raw/partA_test_contacts.csv + 根目录 partA_prediction.csv
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
TEST_CONTACTS_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_test_contacts.csv"
)
PREDICTION_CSV = PROJECT_DIR / "partA_prediction.csv"

SORT_ORDERS = ("prob_desc", "contact_id")


@lru_cache(maxsize=1)
def _roster_frame() -> pd.DataFrame:
    contacts = pd.read_csv(
        TEST_CONTACTS_CSV,
        dtype={"contact_id": str, "customer_id": str, "product_id": str},
    )
    predictions = pd.read_csv(PREDICTION_CSV, dtype={"contact_id": str})
    merged = contacts.merge(predictions, on="contact_id", how="left")
    if merged["response_prob"].isna().any():
        raise RuntimeError("预测文件未覆盖全部测试名单")
    merged["response_prob"] = pd.to_numeric(merged["response_prob"])
    products = pd.read_csv(
        PROJECT_DIR / "src" / "data" / "raw" / "t_product.csv",
        dtype={"product_id": str},
    )[["product_id", "product_name", "risk_level"]]
    merged = merged.merge(products, on="product_id", how="left")
    return merged


def query_roster(
    *,
    page: int = 1,
    size: int = 50,
    channel: str | None = None,
    min_prob: float | None = None,
    sort: str = "prob_desc",
) -> dict:
    """查询响应名单（默认按概率降序）。"""
    if sort not in SORT_ORDERS:
        raise ValueError(f"sort must be one of {SORT_ORDERS}")
    if page < 1 or size < 1 or size > 200:
        raise ValueError("page >= 1, 1 <= size <= 200")

    frame = _roster_frame()
    if channel:
        if channel not in ("sms", "call", "app_push", "manager"):
            raise ValueError(f"unknown channel: {channel}")
        frame = frame[frame["channel"] == channel]
    if min_prob is not None:
        if not 0.0 <= float(min_prob) <= 1.0:
            raise ValueError("min_prob must be in [0, 1]")
        frame = frame[frame["response_prob"] >= float(min_prob)]

    if sort == "prob_desc":
        frame = frame.sort_values(
            ["response_prob", "contact_id"], ascending=[False, True]
        )
    else:
        frame = frame.sort_values("contact_id")

    total = int(len(frame))
    start = (page - 1) * size
    rows = frame.iloc[start : start + size]

    return {
        "total": total,
        "page": page,
        "size": size,
        "customers": [
            {
                "contact_id": row.contact_id,
                "customer_id": row.customer_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "risk_level": row.risk_level,
                "channel": row.channel,
                "contact_date": str(row.contact_date),
                "response_prob": round(float(row.response_prob), 12),
            }
            for row in rows.itertuples()
        ],
    }
