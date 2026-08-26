"""A1 响应名单查询（Tab3 名单区块，前端零计算）。

数据源：
- 提交口径（contact_date=2026-04-15 或缺省）：根目录 partA_prediction.csv（LGBM 提交版）；
- 演示日批（其余日期）：src/data/outputs/roster_daily_demo.json
  （由 scripts/build_daily_roster.py 用 LR 工件按 as-of 重算预生成）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
TEST_CONTACTS_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_test_contacts.csv"
)
PREDICTION_CSV = PROJECT_DIR / "partA_prediction.csv"
STRATEGY_CUSTOMERS_CSV = (
    PROJECT_DIR / "src" / "data" / "raw" / "partA_strategy_customers.csv"
)
ROSTER_DAILY_JSON = (
    PROJECT_DIR / "src" / "data" / "outputs" / "roster_daily_demo.json"
)

SORT_ORDERS = ("prob_desc", "contact_id", "delta_desc")
SUBMITTED_DATE = "2026-04-15"
SCOPE_SUBMITTED = "submitted"
SCOPE_DEMO_ASOF = "demo_asof"


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
    strategy_customers = set(
        pd.read_csv(STRATEGY_CUSTOMERS_CSV, dtype={"customer_id": str})[
            "customer_id"
        ]
    )
    merged["strategy_eligible"] = merged["customer_id"].isin(
        strategy_customers
    )
    return merged


@lru_cache(maxsize=1)
def _daily_demo() -> dict[str, dict[str, dict]]:
    """演示日批缓存：date -> {contact_id: {prob, rank}}。"""
    if not ROSTER_DAILY_JSON.is_file():
        return {}
    data = json.loads(ROSTER_DAILY_JSON.read_text(encoding="utf-8"))
    return data.get("dates", {})


def available_dates() -> list[dict]:
    """返回可选的名单日期：提交口径 + 历史回放日批。"""
    dates = [{"date": SUBMITTED_DATE, "scope": SCOPE_SUBMITTED}]
    for day in sorted(_daily_demo()):
        dates.append({"date": day, "scope": SCOPE_DEMO_ASOF})
    return dates


def query_roster(
    *,
    page: int = 1,
    size: int = 50,
    channel: str | None = None,
    min_prob: float | None = None,
    sort: str = "prob_desc",
    keyword: str | None = None,
    contact_date: str | None = None,
) -> dict:
    """查询响应名单（默认按概率降序）。

    contact_date 为 None 或 2026-04-15 时使用提交口径（LGBM 预测文件）；
    其余日期使用演示日批（LR as-of 重算缓存），响应中带 model_scope 标注。
    """
    if sort not in SORT_ORDERS:
        raise ValueError(f"sort must be one of {SORT_ORDERS}")
    if page < 1 or size < 1 or size > 200:
        raise ValueError("page >= 1, 1 <= size <= 200")

    frame = _roster_frame().copy()
    model_scope = SCOPE_SUBMITTED
    effective_date = SUBMITTED_DATE
    demo_ranks: dict[str, int] = {}
    demo_rank_delta: dict[str, int | None] = {}
    rank_move_count: int | None = None
    if contact_date is not None and contact_date != SUBMITTED_DATE:
        demo = _daily_demo()
        if contact_date not in demo:
            raise ValueError(
                f"演示日批不存在：{contact_date}"
                f"（可用日期：{sorted(demo)}）"
            )
        day_data = demo[contact_date]
        frame["response_prob"] = frame["contact_id"].map(
            {cid: item["prob"] for cid, item in day_data.items()}
        )
        if frame["response_prob"].isna().any():
            raise RuntimeError(
                f"演示日批 {contact_date} 概率缺失，请重新运行 "
                "python -m src.scripts.build_daily_roster"
            )
        demo_ranks = {cid: int(item["rank"]) for cid, item in day_data.items()}
        sorted_days = sorted(demo)
        previous_day = (
            sorted_days[sorted_days.index(contact_date) - 1]
            if sorted_days.index(contact_date) > 0
            else None
        )
        if previous_day:
            previous_ranks = {
                cid: int(item["rank"])
                for cid, item in demo[previous_day].items()
            }
            demo_rank_delta = {
                cid: previous_ranks.get(cid, 0) - demo_ranks.get(cid, 0)
                for cid in demo_ranks
            }
            rank_move_count = sum(
                1 for delta in demo_rank_delta.values() if abs(delta) >= 20
            )
        model_scope = SCOPE_DEMO_ASOF
        effective_date = contact_date
        frame["contact_date"] = contact_date  # 目标日期 = 回放日期
        frame["rank_delta"] = frame["contact_id"].map(
            lambda cid: demo_rank_delta.get(cid)
        )
    else:
        frame["rank_delta"] = None
    if sort == "delta_desc" and model_scope != SCOPE_DEMO_ASOF:
        raise ValueError("sort=delta_desc 仅用于历史回放日期")
    if channel:
        if channel not in ("sms", "call", "app_push", "manager"):
            raise ValueError(f"unknown channel: {channel}")
        frame = frame[frame["channel"] == channel]
    if min_prob is not None:
        if not 0.0 <= float(min_prob) <= 1.0:
            raise ValueError("min_prob must be in [0, 1]")
        frame = frame[frame["response_prob"] >= float(min_prob)]
    if keyword:
        term = keyword.strip().lower()
        if term:
            frame = frame[
                frame["customer_id"].astype(str).str.lower().str.contains(term, na=False)
                | frame["product_id"].astype(str).str.lower().str.contains(term, na=False)
                | frame["product_name"].astype(str).str.lower().str.contains(term, na=False)
            ]

    if sort == "prob_desc":
        frame = frame.sort_values(
            ["response_prob", "contact_id"], ascending=[False, True]
        )
    elif sort == "contact_id":
        frame = frame.sort_values("contact_id")
    else:  # delta_desc：按排名变动绝对值降序（历史回放口径）
        frame["_abs_delta"] = frame["rank_delta"].fillna(0).abs()
        frame = frame.sort_values(
            ["_abs_delta", "response_prob"], ascending=[False, False]
        ).drop(columns="_abs_delta")

    total = int(len(frame))
    start = (page - 1) * size
    rows = frame.iloc[start : start + size]

    return {
        "total": total,
        "page": page,
        "size": size,
        "contact_date": effective_date,
        "model_scope": model_scope,
        "dates": available_dates(),
        "rank_move_count": rank_move_count,
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
                "strategy_eligible": bool(row.strategy_eligible),
                "rank": demo_ranks.get(row.contact_id),
                "rank_delta": demo_rank_delta.get(row.contact_id),
            }
            for row in rows.itertuples()
        ],
    }
