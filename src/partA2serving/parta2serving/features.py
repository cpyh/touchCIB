from __future__ import annotations

import numpy as np
import pandas as pd

from .config import CHANNELS

CAT_COLS = [
    "age_group",
    "city",
    "occupation",
    "income_level",
    "vip_level",
    "channel",
    "product_type",
    "liquidity",
    "risk_match_bin",
    "seg_risk_income",
]

FEATURE_COLUMNS: list[str]  # NUM_COLS + CAT_COLS，见文件末尾赋值

NUM_COLS = [
    "risk_n_c",
    "has_app",
    "log_aum",
    "vip_n",
    "risk_n_p",
    "expected_return",
    "volatility",
    "log_min_invest",
    "duration_days",
    "liq_n",
    "abs_risk_diff",
    "signed_risk_diff",
    "risk_exact_match",
    "risk_within_1",
    "aum_over_min",
    "can_afford",
    "return_over_vol",
    "return_risk_align",
    "app_x_push",
    "vip_x_return",
    "vip_x_risk_p",
    "hold_n",
    "log_hold_amt",
    "held_n",
    "already_held",
    "cust_camp_n",
    "cust_camp_pos",
    "cust_resp_rate",
    "cp_camp_n",
    "cp_camp_pos",
    "cp_resp_rate",
    "prod_resp_rate",
    "chan_resp_rate",
    "prod_chan_resp_rate",
    "seg_prod_rate",
    "seg_type_rate",
    "risk_prod_rate",
    "type_hold_share",
    "ev_login",
    "ev_consult",
    "ev_complaint",
    "ev_active",
]


def _safe_rate(num: pd.Series, den: pd.Series) -> pd.Series:
    return num.astype(float) / den.astype(float).clip(lower=1.0)


# 兼容旧调用名
_safe_rate = _safe_rate


def build_feature_context(
    customer: pd.DataFrame,
    product: pd.DataFrame,
    holding: pd.DataFrame,
    campaign: pd.DataFrame,
    event: pd.DataFrame,
) -> dict:
    cust = customer.copy()
    prod = product.copy()
    if "risk_n" in cust.columns:
        cust = cust.rename(columns={"risk_n": "risk_n_c"})
    if "risk_n" in prod.columns:
        prod = prod.rename(columns={"risk_n": "risk_n_p"})

    vip_map = {"普通": 0, "银卡": 1, "金卡": 2, "钻石": 3}
    cust["vip_n"] = cust["vip_level"].map(vip_map).fillna(0).astype(float)
    cust["seg_risk_income"] = (
        cust["risk_appetite"].astype(str) + "|" + cust["income_level"].astype(str)
    )

    hold_agg = (
        holding.groupby("customer_id")
        .agg(hold_n=("product_id", "nunique"), hold_amt=("amount", "sum"))
        .reset_index()
    )
    held = (
        holding.groupby(["customer_id", "product_id"])
        .size()
        .rename("held_n")
        .reset_index()
    )
    cust_camp = (
        campaign.groupby("customer_id")
        .agg(cust_camp_n=("responded", "size"), cust_camp_pos=("responded", "sum"))
        .reset_index()
    )
    cp_camp = (
        campaign.groupby(["customer_id", "product_id"])
        .agg(cp_camp_n=("responded", "size"), cp_camp_pos=("responded", "sum"))
        .reset_index()
    )
    prod_rate = campaign.groupby("product_id")["responded"].mean().rename("prod_resp_rate")
    chan_rate = campaign.groupby("channel")["responded"].mean().rename("chan_resp_rate")
    prod_chan_rate = (
        campaign.groupby(["product_id", "channel"])["responded"]
        .mean()
        .rename("prod_chan_resp_rate")
        .reset_index()
    )

    # 客群交互响应率
    camp_m = campaign.merge(
        cust[["customer_id", "seg_risk_income", "risk_appetite"]],
        on="customer_id",
        how="left",
    ).merge(prod[["product_id", "product_type"]], on="product_id", how="left")
    seg_prod = (
        camp_m.groupby(["seg_risk_income", "product_id"])["responded"]
        .mean()
        .rename("seg_prod_rate")
        .reset_index()
    )
    seg_type = (
        camp_m.groupby(["seg_risk_income", "product_type"])["responded"]
        .mean()
        .rename("seg_type_rate")
        .reset_index()
    )
    risk_prod = (
        camp_m.groupby(["risk_appetite", "product_id"])["responded"]
        .mean()
        .rename("risk_prod_rate")
        .reset_index()
    )

    type_hold = holding.merge(
        prod[["product_id", "product_type"]], on="product_id", how="left"
    )
    if len(type_hold):
        type_cnt = (
            type_hold.groupby(["customer_id", "product_type"])
            .size()
            .rename("type_cnt")
            .reset_index()
        )
        tot = type_cnt.groupby("customer_id")["type_cnt"].transform("sum")
        type_cnt["type_hold_share"] = type_cnt["type_cnt"] / tot.clip(lower=1)
    else:
        type_cnt = pd.DataFrame(
            columns=["customer_id", "product_type", "type_cnt", "type_hold_share"]
        )

    ev = (
        event.groupby(["customer_id", "event_type"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    ev = ev.rename(columns={c: f"ev_{c}" for c in ev.columns if c != "customer_id"})
    for col in ("ev_login", "ev_consult", "ev_complaint"):
        if col not in ev.columns:
            ev[col] = 0

    hist = hold_agg.merge(cust_camp, on="customer_id", how="outer")
    hist = hist.merge(
        ev[["customer_id", "ev_login", "ev_consult", "ev_complaint"]],
        on="customer_id",
        how="outer",
    )

    return {
        "customer": cust,
        "product": prod,
        "hist": hist,
        "held": held,
        "cp_camp": cp_camp,
        "prod_rate": prod_rate,
        "chan_rate": chan_rate,
        "prod_chan_rate": prod_chan_rate,
        "seg_prod": seg_prod,
        "seg_type": seg_type,
        "risk_prod": risk_prod,
        "type_hold": type_cnt,
    }


def attach_pair_features(base: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    cust_cols = [
        "customer_id",
        "age_group",
        "city",
        "occupation",
        "income_level",
        "vip_level",
        "aum",
        "risk_appetite",
        "risk_n_c",
        "has_app",
        "vip_n",
        "seg_risk_income",
    ]
    prod_cols = [
        "product_id",
        "product_name",
        "product_type",
        "risk_level",
        "expected_return",
        "volatility",
        "min_invest",
        "duration_days",
        "liquidity",
        "risk_n_p",
        "liq_n",
    ]
    df = base.merge(ctx["customer"][cust_cols], on="customer_id", how="left")
    df = df.merge(ctx["product"][prod_cols], on="product_id", how="left")
    df = df.merge(ctx["hist"], on="customer_id", how="left")
    df = df.merge(ctx["held"], on=["customer_id", "product_id"], how="left")
    df = df.merge(ctx["cp_camp"], on=["customer_id", "product_id"], how="left")
    df["prod_resp_rate"] = df["product_id"].map(ctx["prod_rate"])
    df["chan_resp_rate"] = df["channel"].map(ctx["chan_rate"])
    df = df.merge(ctx["prod_chan_rate"], on=["product_id", "channel"], how="left")
    df = df.merge(ctx["seg_prod"], on=["seg_risk_income", "product_id"], how="left")
    df = df.merge(ctx["seg_type"], on=["seg_risk_income", "product_type"], how="left")
    df = df.merge(ctx["risk_prod"], on=["risk_appetite", "product_id"], how="left")
    df = df.merge(
        ctx["type_hold"][["customer_id", "product_type", "type_hold_share"]],
        on=["customer_id", "product_type"],
        how="left",
    )

    for c in [
        "hold_n",
        "hold_amt",
        "held_n",
        "cust_camp_n",
        "cust_camp_pos",
        "cp_camp_n",
        "cp_camp_pos",
        "ev_login",
        "ev_consult",
        "ev_complaint",
        "type_hold_share",
        "vip_n",
    ]:
        df[c] = df[c].fillna(0)

    prior = float(ctx["prod_rate"].mean()) if len(ctx["prod_rate"]) else 0.18
    chan_prior = float(ctx["chan_rate"].mean()) if len(ctx["chan_rate"]) else prior
    for c, p in [
        ("prod_resp_rate", prior),
        ("chan_resp_rate", chan_prior),
        ("prod_chan_resp_rate", prior),
        ("seg_prod_rate", prior),
        ("seg_type_rate", prior),
        ("risk_prod_rate", prior),
    ]:
        df[c] = df[c].fillna(p)

    df["log_aum"] = np.log1p(df["aum"].astype(float))
    df["log_min_invest"] = np.log1p(df["min_invest"].astype(float))
    df["log_hold_amt"] = np.log1p(df["hold_amt"].astype(float))
    df["signed_risk_diff"] = df["risk_n_c"] - df["risk_n_p"]
    df["abs_risk_diff"] = df["signed_risk_diff"].abs()
    df["risk_exact_match"] = (df["abs_risk_diff"] == 0).astype(int)
    df["risk_within_1"] = (df["abs_risk_diff"] <= 1).astype(int)
    df["risk_match_bin"] = np.select(
        [df["abs_risk_diff"] == 0, df["abs_risk_diff"] == 1],
        ["exact", "near"],
        default="far",
    )
    df["aum_over_min"] = df["aum"].astype(float) / df["min_invest"].astype(float).clip(
        lower=1.0
    )
    df["can_afford"] = (df["aum"] >= df["min_invest"]).astype(int)
    df["has_app"] = df["has_app"].fillna(0).astype(int)
    df["already_held"] = (df["held_n"] > 0).astype(int)
    df["cust_resp_rate"] = _safe_rate(df["cust_camp_pos"], df["cust_camp_n"])
    df["cp_resp_rate"] = _safe_rate(df["cp_camp_pos"], df["cp_camp_n"])
    df["return_over_vol"] = df["expected_return"] / df["volatility"].clip(lower=1e-4)
    df["return_risk_align"] = df["expected_return"] * df["risk_n_c"]
    df["app_x_push"] = ((df["channel"] == "app_push") & (df["has_app"] == 1)).astype(int)
    df["vip_x_return"] = df["vip_n"] * df["expected_return"]
    df["vip_x_risk_p"] = df["vip_n"] * df["risk_n_p"]
    df["ev_active"] = df["ev_login"] + df["ev_consult"]
    return df


def build_contact_frame(campaign: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    base = campaign[
        ["contact_id", "customer_id", "product_id", "channel", "contact_date", "responded"]
    ].copy()
    return attach_pair_features(base, ctx)


def build_score_grid(
    customer_ids: list[str] | pd.Series,
    ctx: dict,
    channels: list[str] | None = None,
) -> pd.DataFrame:
    channels = channels or CHANNELS
    ids = pd.Index(customer_ids).unique().tolist()
    base = (
        pd.DataFrame({"customer_id": ids})
        .merge(ctx["product"][["product_id"]], how="cross")
        .merge(pd.DataFrame({"channel": channels}), how="cross")
    )
    return attach_pair_features(base, ctx)


def build_product_grid(
    customer_ids: list[str] | pd.Series,
    ctx: dict,
    channel: str = "manager",
) -> pd.DataFrame:
    """产品级候选（固定渠道，避免渠道信号淹没产品排序）。"""
    ids = pd.Index(customer_ids).unique().tolist()
    base = (
        pd.DataFrame({"customer_id": ids})
        .merge(ctx["product"][["product_id"]], how="cross")
        .assign(channel=channel)
    )
    return attach_pair_features(base, ctx)


def build_product_rank_frame(
    campaign: pd.DataFrame,
    ctx: dict,
    seed: int = 42,
) -> pd.DataFrame:
    """
    下一购导向的 listwise 样本：
    - 每位在窗口内有正响应的客户为一组
    - 相关度：末次正响应产品=3，其他正响应=2，触达未响应=1，未触达=0
    - 固定渠道=manager，专注产品排序
    """
    products = ctx["product"]["product_id"].tolist()
    rows: list[tuple] = []
    for cid, g in campaign.groupby("customer_id"):
        pos_g = g.loc[g["responded"] == 1].sort_values("contact_date")
        if pos_g.empty:
            continue
        last_pos = pos_g.iloc[-1]["product_id"]
        pos = set(pos_g["product_id"])
        contacted = set(g["product_id"])
        for pid in products:
            if pid == last_pos:
                rel = 3
            elif pid in pos:
                rel = 2
            elif pid in contacted:
                rel = 1
            else:
                rel = 0
            rows.append((cid, pid, "manager", rel))
    if not rows:
        return pd.DataFrame()
    base = pd.DataFrame(
        rows, columns=["customer_id", "product_id", "channel", "relevance"]
    )
    base = base.sample(frac=1.0, random_state=seed).sort_values("customer_id")
    base = base.reset_index(drop=True)
    feat = attach_pair_features(base.drop(columns=["relevance"]), ctx)
    feat["relevance"] = base["relevance"].to_numpy()
    return feat


FEATURE_COLUMNS = NUM_COLS + CAT_COLS


def matrix_from_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    use = df[FEATURE_COLUMNS].copy()
    for c in CAT_COLS:
        use[c] = use[c].astype(str).astype("category")
    return use, FEATURE_COLUMNS
