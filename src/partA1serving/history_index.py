"""在线历史特征索引：把离线的全表聚合改为 O(log n) 查询。

为什么需要
----------
`features_history.build_history_features` 面向离线批量设计：对整张历史表
做 groupby + cumsum，一次算完 5 万行。用在单条在线请求上是 O(全表)，
实测单次约 3.3 秒，完全不可用。

本模块在服务启动时**一次性**把历史表压成"按分组键排序的日期数组 + 前缀和"，
之后每次查询只需二分定位，单次约 0.1 ms。

一致性保证
----------
索引的语义必须与离线实现**逐位等价**，否则在线与离线打分会不一致。
关键点：
  1. 严格小于 as-of 日期（`searchsorted(..., side="left")` 取左侧前缀和）；
  2. 贝叶斯平滑公式与平滑强度直接复用 `features_history` 的实现与常量；
  3. 未命中分组时前缀和为 0，平滑公式自然退化为先验（冷启动）。
`tests/test_serving.py` 会对随机抽样逐行比对在线与离线结果。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import features_history as H


class _GroupIndex:
    """单个分组维度的索引：分组键 -> (升序日期数组, 次数前缀和, 命中数前缀和)。"""

    __slots__ = ("_table",)

    def __init__(self, source: pd.DataFrame, keys: list[str], label: str) -> None:
        work = source[[*keys, "contact_date"]].copy()
        work["_y"] = source[label].astype(float).to_numpy()
        daily = (
            work.groupby([*keys, "contact_date"], sort=True)
            .agg(_n=("_y", "size"), _s=("_y", "sum"))
            .reset_index()
        )
        grp = daily.groupby(keys, sort=False)
        daily["_cum_n"] = grp["_n"].cumsum()
        daily["_cum_s"] = grp["_s"].cumsum()

        self._table: dict[tuple, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for key, g in daily.groupby(keys, sort=False):
            k = key if isinstance(key, tuple) else (key,)
            self._table[k] = (
                g["contact_date"].to_numpy(),
                g["_cum_n"].to_numpy(dtype=np.int64),
                g["_cum_s"].to_numpy(dtype=np.int64),
            )

    def query(self, key: tuple, as_of: pd.Timestamp) -> tuple[int, int]:
        """返回严格早于 as_of 的 (次数, 命中数)。未命中返回 (0, 0)。"""
        entry = self._table.get(key)
        if entry is None:
            return 0, 0
        dates, cum_n, cum_s = entry
        pos = int(np.searchsorted(dates, np.datetime64(as_of), side="left"))
        if pos == 0:
            return 0, 0
        return int(cum_n[pos - 1]), int(cum_s[pos - 1])

    def last_date_before(self, key: tuple, as_of: pd.Timestamp) -> pd.Timestamp | None:
        entry = self._table.get(key)
        if entry is None:
            return None
        dates = entry[0]
        pos = int(np.searchsorted(dates, np.datetime64(as_of), side="left"))
        return pd.Timestamp(dates[pos - 1]) if pos > 0 else None


class HistoryIndex:
    """全部历史特征的在线索引。构造一次，之后重复查询。"""

    def __init__(
        self,
        contacts: pd.DataFrame,
        holding: pd.DataFrame,
        events: pd.DataFrame,
        prior: float,
        label: str = "responded",
        product_types: pd.Series | None = None,
    ) -> None:
        self.prior = float(prior)
        # 在线平台由数据源注入产品类型，避免 HistoryIndex 隐式回读 CSV。
        # 保留默认加载仅用于兼容队友原有的独立调用方式。
        self.ptype_map = (
            product_types.copy() if product_types is not None else H.load_product_types()
        )

        src = contacts.copy()
        src["_ptype"] = src["product_id"].map(self.ptype_map)

        self._by_cust = _GroupIndex(src, ["customer_id"], label)
        self._by_cust_ch = _GroupIndex(src, ["customer_id", "channel"], label)
        self._by_cust_pt = _GroupIndex(src, ["customer_id", "_ptype"], label)
        self._by_prod = _GroupIndex(src, ["product_id"], label)

        # 持仓：按客户聚成 (买入日, 产品, 金额, 类型) 数组，查询时按日期过滤
        h = holding[["customer_id", "product_id", "buy_date", "amount"]].copy()
        h["_ptype"] = h["product_id"].map(self.ptype_map)
        h = h.sort_values("buy_date")
        self._holdings: dict[str, np.ndarray] = {
            cid: g[["buy_date", "product_id", "amount", "_ptype"]].to_numpy()
            for cid, g in h.groupby("customer_id")
        }

        ev = events[events["event_type"].isin(H.EVENT_TYPES)].sort_values("event_date")
        self._events: dict[str, np.ndarray] = {
            cid: g[["event_date", "event_type"]].to_numpy() for cid, g in ev.groupby("customer_id")
        }

    # ------------------------------------------------------------

    def build_row(
        self,
        customer_id: str,
        product_id: str,
        channel: str,
        as_of: pd.Timestamp,
    ) -> dict[str, float]:
        """返回一行历史特征（键与 features_history.get_history_columns() 一致）。"""
        ptype = self.ptype_map.get(product_id)

        c_cnt, c_hit = self._by_cust.query((customer_id,), as_of)
        ch_cnt, ch_hit = self._by_cust_ch.query((customer_id, channel), as_of)
        pt_cnt, pt_hit = self._by_cust_pt.query((customer_id, ptype), as_of)
        p_cnt, p_hit = self._by_prod.query((product_id,), as_of)

        def rate(hit: int, cnt: int) -> float:
            return float(H._smooth_rate(np.array([hit]), np.array([cnt]), self.prior)[0])

        last = self._by_cust.last_date_before((customer_id,), as_of)
        days_since = 999 if last is None else int((as_of - last).days)

        owns_prod = hold_cnt = owns_type = 0
        hold_amt = 0.0
        rows = self._holdings.get(customer_id)
        if rows is not None:
            mask = rows[:, 0] < np.datetime64(as_of)
            if mask.any():
                sub = rows[mask]
                hold_cnt = len(sub)
                hold_amt = float(sub[:, 2].sum())
                owns_prod = int((sub[:, 1] == product_id).any())
                owns_type = int((sub[:, 3] == ptype).any())

        consult = complaint = 0
        erows = self._events.get(customer_id)
        if erows is not None:
            lo = np.datetime64(as_of - pd.Timedelta(days=H.EVENT_WINDOW_DAYS))
            hi = np.datetime64(as_of)
            emask = (erows[:, 0] >= lo) & (erows[:, 0] < hi)
            if emask.any():
                types = erows[emask, 1]
                consult = int((types == "consult").sum())
                complaint = int((types == "complaint").sum())

        return {
            "cust_hist_cnt": c_cnt,
            "cust_hist_resp": c_hit,
            "cust_hist_rate": rate(c_hit, c_cnt),
            "cust_ch_cnt": ch_cnt,
            "cust_ch_rate": rate(ch_hit, ch_cnt),
            "cust_ptype_cnt": pt_cnt,
            "cust_ptype_rate": rate(pt_hit, pt_cnt),
            "prod_hist_cnt": p_cnt,
            "prod_hist_rate": rate(p_hit, p_cnt),
            "owns_this_product": owns_prod,
            "hold_cnt": hold_cnt,
            "hold_amount_log": float(np.log1p(hold_amt)),
            "owns_same_type": owns_type,
            "consult_30d": consult,
            "complaint_30d": complaint,
            "days_since_last_contact": days_since,
        }
