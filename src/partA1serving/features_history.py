"""Part A 历史统计特征（第 3 步）。

与 `features_a1.py` 的区别
-------------------------
`features_a1.py` 只做"拼完就有"和"当前行自算"的特征，没有时间维度问题。
本模块做的是**跨行聚合**——回答"这个客户/这个组合在过去表现如何"，
因此必须严格处理时间边界，否则会时间穿越或目标泄漏。

三条铁律
--------
1. **严格小于**：只统计 `date < contact_date` 的信息。
   同一客户同一天的其他触达**不计入**（训练集 427 组、测试集 2100 个客户存在此情况，
   用 `<=` 会让它们互相看到标签）。
2. **排除自身**：当前行的 `responded` 绝不能进入自己的历史统计。
   实现上用 `cumsum() - 自身值`，天然满足。
3. **贝叶斯平滑**：历史响应率用 `(命中数 + k×先验) / (次数 + k)`。
   - 冷启动自动处理：次数=0 时结果恒为先验，无需写 if 分支；
   - 小样本自动收缩：只触达 1 次且响应，naive 会给 100%，平滑后为 0.259。
   实测 k=10 时与标签的相关系数最高（k=0:0.0995 → k=10:0.1135）。

训练 / 推理两种模式
------------------
- 训练：`history_source=None`，历史来自 contacts 自身（逐行 as-of 展开）。
- 推理：`history_source=训练集`，测试集本身无标签，历史全部来自训练集。
  测试日 2026-04-15 晚于所有训练数据，故等价于使用全部训练历史。
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import config


# ================================================================ 参数

# 贝叶斯平滑强度。实测 k=10 时历史响应率与标签的相关系数最高。
SMOOTH_K = 10.0

# 事件窗口（天）。只用 consult / complaint：
# 实测 consult 近30天 +0.0240、complaint 近30天 -0.0150，方向符合业务直觉；
# login 近30天仅 -0.0049（几乎无信号），故不采用。
EVENT_WINDOW_DAYS = 30
EVENT_TYPES = ("consult", "complaint")


# ================================================================ 特征清单

HISTORY_NUMERIC = [
    # 客户维度的历史触达表现
    "cust_hist_cnt",  # 历史被触达次数（=0 天然表示"无历史"，无需额外标记列）
    "cust_hist_resp",  # 历史响应次数
    "cust_hist_rate",  # 历史响应率（贝叶斯平滑）
    # 客户 × 渠道
    "cust_ch_cnt",
    "cust_ch_rate",
    # 客户 × 产品类型
    "cust_ptype_cnt",
    "cust_ptype_rate",
    # 产品维度
    "prod_hist_cnt",
    "prod_hist_rate",
    # 持仓画像（as-of）
    "owns_this_product",
    "hold_cnt",
    "hold_amount_log",
    "owns_same_type",
    # 行为事件（as-of，窗口内）
    "consult_30d",
    "complaint_30d",
    # 触达节奏
    "days_since_last_contact",
]


def get_history_columns() -> list[str]:
    return list(HISTORY_NUMERIC)


# ================================================================ 数据加载


def load_holding() -> pd.DataFrame:
    return pd.read_csv(os.path.join(config.DATA_DIR, "t_holding.csv"), parse_dates=["buy_date"])


def load_events() -> pd.DataFrame:
    return pd.read_csv(os.path.join(config.DATA_DIR, "t_event.csv"), parse_dates=["event_date"])


def load_product_types() -> pd.Series:
    """product_id -> product_type"""
    prod = pd.read_csv(os.path.join(config.DATA_DIR, "t_product.csv"))
    return pd.Series(prod["product_type"].to_numpy(), index=prod["product_id"])


# ================================================================ 工具


def _smooth_rate(hits: np.ndarray, counts: np.ndarray, prior: float) -> np.ndarray:
    """贝叶斯平滑响应率：(hits + k*prior) / (counts + k)。

    counts=0 时结果恒为 prior，冷启动自动处理。
    """
    return (hits + SMOOTH_K * prior) / (counts + SMOOTH_K)


def _asof_cumulative(
    frame: pd.DataFrame,
    group_keys: list[str],
    label: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """按 group_keys 分组，计算每行"严格早于自己 contact_date"的累计次数与累计命中数。

    关键点：同一分组内 contact_date 相同的行必须得到**相同**的结果
    （即同日互不可见）。做法是先按日期聚合成"日级别"的累计量，再按日期回填。

    Args:
        frame: 需含 contact_date 与 group_keys
        label: 与 frame 等长的标签数组；为 None 时只统计次数（命中数返回全 0）

    Returns:
        (counts, hits) 两个与 frame 等长的数组
    """
    work = frame[[*group_keys, "contact_date"]].copy()
    work["_row"] = np.arange(len(work))
    work["_y"] = 0.0 if label is None else np.asarray(label, dtype=float)

    # 先聚合到 (group, date) 粒度
    daily = (
        work.groupby([*group_keys, "contact_date"], sort=True)
        .agg(_n=("_y", "size"), _s=("_y", "sum"))
        .reset_index()
    )
    # 组内按日期累计，再 shift 一位 -> 得到"严格早于当天"的累计量
    g = daily.groupby(group_keys, sort=False)
    daily["_cum_n"] = g["_n"].cumsum() - daily["_n"]
    daily["_cum_s"] = g["_s"].cumsum() - daily["_s"]

    merged = work.merge(
        daily[[*group_keys, "contact_date", "_cum_n", "_cum_s"]],
        on=[*group_keys, "contact_date"],
        how="left",
    )
    merged = merged.sort_values("_row")
    return (
        merged["_cum_n"].to_numpy(dtype=np.int64),
        merged["_cum_s"].to_numpy(dtype=np.int64),
    )


def _asof_lookup(
    contacts: pd.DataFrame,
    source: pd.DataFrame,
    group_keys: list[str],
    label_col: str | None,
) -> tuple[np.ndarray, np.ndarray]:
    """推理模式：历史来自另一张表（source），只取 source 中严格早于 contact_date 的记录。

    实现为按分组的排序合并（merge_asof 的等价逻辑，但保证严格小于）。
    """
    src = source[[*group_keys, "contact_date"]].copy()
    src["_y"] = 0.0 if label_col is None else source[label_col].astype(float).to_numpy()
    daily = (
        src.groupby([*group_keys, "contact_date"], sort=True)
        .agg(_n=("_y", "size"), _s=("_y", "sum"))
        .reset_index()
    )
    g = daily.groupby(group_keys, sort=False)
    # 含当天的累计量；查询时用 searchsorted 找"严格小于"的位置
    daily["_cum_n"] = g["_n"].cumsum()
    daily["_cum_s"] = g["_s"].cumsum()

    counts = np.zeros(len(contacts), dtype=np.int64)
    hits = np.zeros(len(contacts), dtype=np.int64)

    lookup: dict[tuple, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for key, grp in daily.groupby(group_keys, sort=False):
        k = key if isinstance(key, tuple) else (key,)
        lookup[k] = (
            grp["contact_date"].to_numpy(),
            grp["_cum_n"].to_numpy(),
            grp["_cum_s"].to_numpy(),
        )

    keys_arr = [contacts[c].to_numpy() for c in group_keys]
    dates = contacts["contact_date"].to_numpy()
    for i in range(len(contacts)):
        k = tuple(arr[i] for arr in keys_arr)
        entry = lookup.get(k)
        if entry is None:
            continue
        src_dates, cum_n, cum_s = entry
        # 严格小于：找第一个 >= 当前日期的位置，取其左侧累计量
        pos = int(np.searchsorted(src_dates, dates[i], side="left"))
        if pos > 0:
            counts[i] = cum_n[pos - 1]
            hits[i] = cum_s[pos - 1]
    return counts, hits


# ================================================================ 核心


def build_history_features(
    contacts: pd.DataFrame,
    holding: pd.DataFrame,
    events: pd.DataFrame,
    label_col: str | None = "responded",
    history_source: pd.DataFrame | None = None,
    prior: float | None = None,
) -> pd.DataFrame:
    """构造历史统计特征。

    Args:
        contacts: 目标触达记录（训练集或测试集），需含
                  contact_id / customer_id / product_id / channel / contact_date
        holding:  t_holding
        events:   t_event
        label_col: contacts 中的标签列名；测试集无标签时传 None
        history_source: 历史来源表。None 表示用 contacts 自身（训练模式）；
                        推理时传入训练集。
        prior: 贝叶斯平滑的先验。默认从标签均值推断；
               显式传入可保证训练/推理使用同一先验（也便于测试固定该值）。

    Returns:
        含 contact_id 与全部历史特征的 DataFrame，行数与 contacts 一致。
    """
    df = contacts.reset_index(drop=True).copy()
    ptype_map = load_product_types()
    df["_ptype"] = df["product_id"].map(ptype_map)

    if history_source is not None:
        src = history_source.reset_index(drop=True).copy()
        src["_ptype"] = src["product_id"].map(ptype_map)
        src_label = "responded"
        inferred_prior = float(src["responded"].mean())
    else:
        src = df
        if label_col is None:
            raise ValueError("训练模式必须提供 label_col")
        src_label = label_col
        inferred_prior = float(df[label_col].mean())

    prior_value = inferred_prior if prior is None else float(prior)

    out = pd.DataFrame({"contact_id": df["contact_id"].to_numpy()})

    def counts_hits(keys: list[str]) -> tuple[np.ndarray, np.ndarray]:
        if history_source is None:
            labels = df[src_label].to_numpy() if src_label else None
            return _asof_cumulative(df, keys, labels)
        return _asof_lookup(df, src, keys, src_label)

    # ---------------- 客户维度
    c_cnt, c_hit = counts_hits(["customer_id"])
    out["cust_hist_cnt"] = c_cnt
    out["cust_hist_resp"] = c_hit
    out["cust_hist_rate"] = _smooth_rate(c_hit, c_cnt, prior_value)

    # ---------------- 客户 × 渠道
    ch_cnt, ch_hit = counts_hits(["customer_id", "channel"])
    out["cust_ch_cnt"] = ch_cnt
    out["cust_ch_rate"] = _smooth_rate(ch_hit, ch_cnt, prior_value)

    # ---------------- 客户 × 产品类型
    pt_cnt, pt_hit = counts_hits(["customer_id", "_ptype"])
    out["cust_ptype_cnt"] = pt_cnt
    out["cust_ptype_rate"] = _smooth_rate(pt_hit, pt_cnt, prior_value)

    # ---------------- 产品维度
    p_cnt, p_hit = counts_hits(["product_id"])
    out["prod_hist_cnt"] = p_cnt
    out["prod_hist_rate"] = _smooth_rate(p_hit, p_cnt, prior_value)

    # ---------------- 距上次触达天数
    out["days_since_last_contact"] = _days_since_last(df, src, history_source is None)

    # ---------------- 持仓（as-of）
    hold_feats = _holding_features(df, holding, ptype_map)
    for col, val in hold_feats.items():
        out[col] = val

    # ---------------- 事件（as-of）
    ev_feats = _event_features(df, events)
    for col, val in ev_feats.items():
        out[col] = val

    return out[["contact_id", *get_history_columns()]]


def _days_since_last(df: pd.DataFrame, src: pd.DataFrame, is_train: bool) -> np.ndarray:
    """距该客户上一次被触达的天数。无历史时用一个大值（表示"很久没联系/从未联系"）。"""
    NO_HISTORY = 999

    prev_date = pd.Series(pd.NaT, index=df.index)
    if is_train:
        # 组内按日期取"上一个不同日期"
        tmp = df[["customer_id", "contact_date"]].copy()
        tmp["_row"] = np.arange(len(tmp))
        daily = (
            tmp.groupby(["customer_id", "contact_date"], sort=True).size().reset_index(name="_n")
        )
        daily["_prev"] = daily.groupby("customer_id", sort=False)["contact_date"].shift(1)
        merged = tmp.merge(
            daily[["customer_id", "contact_date", "_prev"]],
            on=["customer_id", "contact_date"],
            how="left",
        ).sort_values("_row")
        prev_date = merged["_prev"].reset_index(drop=True)
    else:
        # 推理模式：从 src 中取"严格早于当前日期"的最晚一次触达。
        # 注意不能直接用该客户的全局最晚日期再过滤——若全局最晚日期 >= 当前日期，
        # 会把本应可用的更早历史一并作废，错误地退化为 NO_HISTORY。
        src_daily = (
            src[["customer_id", "contact_date"]]
            .drop_duplicates()
            .sort_values(["customer_id", "contact_date"])
        )
        by_cust: dict[str, np.ndarray] = {
            cid: g["contact_date"].to_numpy()
            for cid, g in src_daily.groupby("customer_id", sort=False)
        }
        cust_arr = df["customer_id"].to_numpy()
        date_arr = df["contact_date"].to_numpy()
        prev_vals = np.full(len(df), np.datetime64("NaT"), dtype="datetime64[ns]")
        for i in range(len(df)):
            dates = by_cust.get(cust_arr[i])
            if dates is None:
                continue
            pos = int(np.searchsorted(dates, date_arr[i], side="left"))
            if pos > 0:
                prev_vals[i] = dates[pos - 1]
        prev_date = pd.Series(prev_vals, index=df.index)

    delta = (df["contact_date"] - prev_date).dt.days
    return delta.fillna(NO_HISTORY).astype("int32").to_numpy()


def _holding_features(
    df: pd.DataFrame, holding: pd.DataFrame, ptype_map: pd.Series
) -> dict[str, np.ndarray]:
    """持仓画像：只统计 buy_date < contact_date 的持仓。"""
    n = len(df)
    owns_prod = np.zeros(n, dtype=np.int8)
    hold_cnt = np.zeros(n, dtype=np.int32)
    hold_amt = np.zeros(n, dtype=np.float64)
    owns_type = np.zeros(n, dtype=np.int8)

    h = holding[["customer_id", "product_id", "buy_date", "amount"]].copy()
    h["_ptype"] = h["product_id"].map(ptype_map)

    by_cust: dict[str, np.ndarray] = {
        cid: g[["buy_date", "product_id", "amount", "_ptype"]].to_numpy()
        for cid, g in h.groupby("customer_id")
    }

    cust_arr = df["customer_id"].to_numpy()
    prod_arr = df["product_id"].to_numpy()
    ptype_arr = df["_ptype"].to_numpy()
    date_arr = df["contact_date"].to_numpy()

    for i in range(n):
        rows = by_cust.get(cust_arr[i])
        if rows is None:
            continue
        mask = rows[:, 0] < date_arr[i]
        if not mask.any():
            continue
        sub = rows[mask]
        hold_cnt[i] = len(sub)
        hold_amt[i] = float(sub[:, 2].sum())
        owns_prod[i] = int((sub[:, 1] == prod_arr[i]).any())
        owns_type[i] = int((sub[:, 3] == ptype_arr[i]).any())

    return {
        "owns_this_product": owns_prod,
        "hold_cnt": hold_cnt,
        "hold_amount_log": np.log1p(hold_amt),
        "owns_same_type": owns_type,
    }


def _event_features(df: pd.DataFrame, events: pd.DataFrame) -> dict[str, np.ndarray]:
    """行为事件计数：窗口内且严格早于 contact_date。"""
    n = len(df)
    out = {f"{t}_{EVENT_WINDOW_DAYS}d": np.zeros(n, dtype=np.int32) for t in EVENT_TYPES}

    ev = events[events["event_type"].isin(EVENT_TYPES)]
    by_cust: dict[str, np.ndarray] = {
        cid: g[["event_date", "event_type"]].to_numpy() for cid, g in ev.groupby("customer_id")
    }

    cust_arr = df["customer_id"].to_numpy()
    date_arr = df["contact_date"].to_numpy()
    window = np.timedelta64(EVENT_WINDOW_DAYS, "D")

    for i in range(n):
        rows = by_cust.get(cust_arr[i])
        if rows is None:
            continue
        hi = date_arr[i]
        lo = hi - window
        mask = (rows[:, 0] >= lo) & (rows[:, 0] < hi)
        if not mask.any():
            continue
        types = rows[mask, 1]
        for t in EVENT_TYPES:
            out[f"{t}_{EVENT_WINDOW_DAYS}d"][i] = int((types == t).sum())
    return out


def describe_history_features() -> str:
    return (
        f"历史统计特征 {len(get_history_columns())} 个"
        f"（贝叶斯平滑 k={SMOOTH_K:g}，事件窗口 {EVENT_WINDOW_DAYS} 天）:\n"
        f"  {', '.join(get_history_columns())}"
    )
