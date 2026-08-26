"""A2 评测标签：L1/L2/L3 在同一时间切分下的不同「下一购」定义。"""
from __future__ import annotations

from typing import Literal

import pandas as pd

LabelMode = Literal["L1", "L2", "L3"]

LABEL_MODE_DESC: dict[str, str] = {
    "L1": "label_cutoff 后首次 campaign 正响应产品 (responded=1)",
    "L2": "label_cutoff 后首次新持仓 (buy_date≥cutoff 且 as-of 未持有)",
    "L3": "L1 且 as-of 未持有该产品 (正响应 + 新购)",
}


def held_pairs_before(holding: pd.DataFrame, as_of: pd.Timestamp) -> set[tuple[str, str]]:
    h = holding.loc[holding["buy_date"] < as_of]
    return set(zip(h["customer_id"].astype(str), h["product_id"].astype(str)))


def make_label_table(
    campaign: pd.DataFrame,
    holding: pd.DataFrame,
    label_cutoff: pd.Timestamp,
    mode: LabelMode | str = "L2",
) -> pd.DataFrame:
    """返回列：customer_id, label_product, label_date, label_source。"""
    mode = str(mode).upper()
    if mode not in LABEL_MODE_DESC:
        raise ValueError(f"unknown label mode {mode}, use L1/L2/L3")

    lab_ts = pd.Timestamp(label_cutoff)
    held = held_pairs_before(holding, lab_ts)

    if mode == "L1":
        te = campaign.loc[
            (campaign["contact_date"] >= lab_ts) & (campaign["responded"] == 1)
        ].sort_values(["customer_id", "contact_date", "contact_id"])
        out = (
            te.groupby("customer_id", as_index=False)
            .first()[["customer_id", "product_id", "contact_date"]]
            .rename(
                columns={
                    "product_id": "label_product",
                    "contact_date": "label_date",
                }
            )
        )
        out["label_source"] = "campaign_response"
        return out

    if mode == "L2":
        new = holding.loc[holding["buy_date"] >= lab_ts].copy()
        new = new.sort_values(["customer_id", "buy_date", "holding_id"])
        rows = []
        for r in new.itertuples(index=False):
            key = (str(r.customer_id), str(r.product_id))
            if key in held:
                continue
            rows.append(
                {
                    "customer_id": r.customer_id,
                    "label_product": r.product_id,
                    "label_date": r.buy_date,
                    "label_source": "new_holding",
                }
            )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "customer_id",
                    "label_product",
                    "label_date",
                    "label_source",
                ]
            )
        df = pd.DataFrame(rows)
        return (
            df.sort_values(["customer_id", "label_date"])
            .groupby("customer_id", as_index=False)
            .first()
        )

    # L3: L1 filtered by not held before cutoff
    l1 = make_label_table(campaign, holding, lab_ts, "L1")
    if l1.empty:
        return l1
    mask = [
        (str(r.customer_id), str(r.label_product)) not in held
        for r in l1.itertuples(index=False)
    ]
    out = l1.loc[mask].copy()
    out["label_source"] = "response_new_product"
    return out


def label_overlap_stats(
    labels_by_mode: dict[str, pd.DataFrame],
) -> list[dict]:
    """两两标签一致率（在共有客户上）。"""
    rows: list[dict] = []
    modes = sorted(labels_by_mode.keys())
    for i, a in enumerate(modes):
        for b in modes[i + 1:]:
            la = labels_by_mode[a].set_index("customer_id")
            lb = labels_by_mode[b].set_index("customer_id")
            common = la.index.intersection(lb.index)
            if len(common) == 0:
                rows.append(
                    {
                        "mode_a": a,
                        "mode_b": b,
                        "n_common": 0,
                        "product_match_rate": 0.0,
                    }
                )
                continue
            match = (la.loc[common]["label_product"] == lb.loc[common]["label_product"]).mean()
            rows.append(
                {
                    "mode_a": a,
                    "mode_b": b,
                    "n_common": int(len(common)),
                    "product_match_rate": float(match),
                }
            )
    return rows
