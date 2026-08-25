"""持有产品协同过滤（item-based co-holding）。

数据证据（t_campaign 验证）：推荐产品与客户历史持仓相似度越高，
响应率越高（无信号 16.5% → 中相似 24.3%，+47%）。与"已持有精确匹配
（2 倍响应）"组成两级推荐信号：精确持有由队友的排序特征处理，
本模块提供泛化的邻居产品相似度信号。
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import pandas as pd


def build_co_holding_similarity(
    holdings: pd.DataFrame, as_of: date
) -> pd.DataFrame:
    """构建产品共持相似矩阵。

    参数 holdings 至少包含列 customer_id / product_id / buy_date。

    相似度定义（非对称，"持有 i 的客户中有多少比例也持有 j"）：

        sim(i -> j) = 同时持有 i、j 的客户数 / 持有 i 的客户数

    as-of 截断：只统计 buy_date 严格早于 as_of 的持仓。
    """
    frame = holdings[["customer_id", "product_id", "buy_date"]].copy()
    frame["buy_date"] = pd.to_datetime(frame["buy_date"], errors="raise")
    valid = frame[frame["buy_date"] < pd.Timestamp(as_of)]
    if valid.empty:
        return pd.DataFrame(
            columns=["product_id_i", "product_id_j", "similarity"]
        )

    pairs = (
        valid[["customer_id", "product_id"]]
        .drop_duplicates()
        .rename(columns={"product_id": "product_id_i"})
    )
    joint = pairs.merge(
        pairs.rename(columns={"product_id_i": "product_id_j"}),
        on="customer_id",
    )
    joint = joint[joint["product_id_i"] != joint["product_id_j"]]

    co_holders = (
        joint.groupby(["product_id_i", "product_id_j"], sort=False)
        .size()
        .rename("co_holders")
        .reset_index()
    )
    holders_i = (
        valid.groupby("product_id", sort=False)
        .size()
        .rename("holders_i")
        .reset_index()
        .rename(columns={"product_id": "product_id_i"})
    )
    result = co_holders.merge(holders_i, on="product_id_i", how="left")
    result["similarity"] = result["co_holders"] / result["holders_i"]
    return (
        result[["product_id_i", "product_id_j", "similarity"]]
        .sort_values(["product_id_i", "similarity"], ascending=[True, False])
        .reset_index(drop=True)
    )


def customer_cf_scores(
    similarity: pd.DataFrame,
    customer_holdings: Mapping[str, Sequence[str]],
    product_ids: Sequence[str],
) -> dict[tuple[str, str], float]:
    """为每个客户计算 (customer_id, product_id) -> 最大相似度。

    cf_score(c, j) = max{ sim(i -> j) : i 属于客户 c 的持仓 }

    规则：
    - 只统计客户未持有的产品 j（已持有的走"精确持有"信号，不重复计）；
    - 无持仓客户不产生任何信号（冷启动，得 0）；
    - 相似度缺失视为 0。
    """
    lookup: dict[tuple[str, str], float] = {}
    if not similarity.empty:
        lookup = {
            (row.product_id_i, row.product_id_j): float(row.similarity)
            for row in similarity.itertuples(index=False)
        }

    scores: dict[tuple[str, str], float] = {}
    for customer_id, held in customer_holdings.items():
        held_set = set(held)
        if not held_set:
            continue
        for product_id in product_ids:
            if product_id in held_set:
                continue
            best = max(
                (lookup.get((i, product_id), 0.0) for i in held_set),
                default=0.0,
            )
            if best > 0.0:
                scores[(customer_id, product_id)] = best
    return scores
