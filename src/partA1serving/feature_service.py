"""在线特征服务：把一条预测请求装配成模型可用的特征行。

设计要点
--------
1. **两种调用模式**（对应题面 Part D 的两个 Tab）：
   - 已有客户：只需 `customer_id`，服务端查 `t_customer` 取画像；
   - 新客进件：库中无此人，调用方传入画像字段，历史特征走冷启动。

2. **复用离线特征代码，不另写一套**。
   `features_a1.build_features` 与 `features_history.build_history_features`
   原样调用，这是保证在线/离线一致的唯一可靠办法——
   若在线重写一遍派生逻辑，两边迟早会漂移，且这类 bug 极难发现。

3. **as-of 语义保持不变**。请求可选传 `contact_date`；未传时用模型元数据里的
   `as_of_date`（训练数据最晚日期）。历史统计一律只取严格早于该日期的记录。

4. **参考数据在服务启动时载入内存**。三张表合计约 7.2 万行，占用很小；
   如此可避免每次请求读盘。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import config
from . import features_a1 as F
from . import features_history as H
from .data_source import A1DataSource, CsvDataSource
from .history_index import HistoryIndex

# 新客进件时必须由调用方提供的客户画像字段
REQUIRED_CUSTOMER_FIELDS = (
    "age_group",
    "city",
    "occupation",
    "income_level",
    "register_date",
    "aum",
    "risk_appetite",
    "vip_level",
    "has_app",
)


class FeatureAssemblyError(ValueError):
    """请求字段缺失或非法。区别于内部错误，便于调用方定位。"""


@dataclass
class PredictRequest:
    """一条预测请求。

    Attributes:
        product_id: 拟推荐的产品，必填，须属于产品池 P001~P030。
        channel: 触达渠道，必填，须属于 sms/call/app_push/manager。
        customer_id: 已有客户 ID。提供时服务端查库取画像与历史。
        contact_date: as-of 基准日，可选。未提供时用模型的 as_of_date。
        customer: 新客画像。当 customer_id 为空（或库中不存在）时必填。
    """

    product_id: str
    channel: str
    customer_id: str | None = None
    contact_date: str | None = None
    customer: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureBundle:
    """装配结果。"""

    frame: pd.DataFrame  # 单行特征表
    mode: str  # "existing_customer" 或 "new_customer"
    as_of: pd.Timestamp
    history_available: bool  # 历史特征是否来自真实数据（False = 冷启动默认值）


class FeatureService:
    """在线特征装配器。构造时载入参考数据并预建索引，之后可重复调用。

    history_cutoff 的作用（演示模型的关键约束）
    -------------------------------------------
    demo 模型只用 < 2026-02-01 的数据训练。若在线特征却能看到 2026-02 之后的
    历史触达标签，就等于让模型间接接触到训练时不该见到的答案，演示指标会虚高。
    因此构造索引时按 history_cutoff 过滤触达表，从数据源头切断这种可能。

    注意只过滤 t_campaign（它携带 responded 标签）。t_holding / t_event 不含
    标签，保留全量并在查询时按请求 as-of 截断即可 —— 这与训练期的口径一致。
    """

    def __init__(
        self,
        prior: float,
        default_as_of: str,
        history_cutoff: str | None = None,
        data_source: A1DataSource | None = None,
    ) -> None:
        self.prior = float(prior)
        self.default_as_of = pd.Timestamp(default_as_of)
        self.history_cutoff = pd.Timestamp(history_cutoff) if history_cutoff else None

        # 参考数据一次性载入内存。默认保留 CSV 行为，Flask 平台显式注入 DWD 数据源。
        self.data_source = data_source or CsvDataSource()
        bundle = self.data_source.load(history_cutoff=history_cutoff)
        self.customer = bundle.customers
        self.product = bundle.products
        self.contacts = bundle.campaigns
        self.holding = bundle.holdings
        self.events = bundle.events

        self._customer_index = self.customer.set_index("customer_id")
        self._product_ids = set(self.product["product_id"])
        self._known_customers = set(self.customer["customer_id"])

        # 历史特征索引：启动时预建，把单条查询从 O(全表) 降到 O(log n)
        product_types = pd.Series(
            self.product["product_type"].to_numpy(),
            index=self.product["product_id"],
        )
        self.history = HistoryIndex(
            self.contacts,
            self.holding,
            self.events,
            prior=self.prior,
            product_types=product_types,
        )
        self._history_columns = H.get_history_columns()

    # ------------------------------------------------------------ 校验

    def _validate(self, req: PredictRequest) -> None:
        if not req.product_id:
            raise FeatureAssemblyError("product_id 不能为空")
        if req.product_id not in self._product_ids:
            raise FeatureAssemblyError(
                f"未知 product_id={req.product_id!r}，须属于产品池 P001~P030"
            )
        if not req.channel:
            raise FeatureAssemblyError("channel 不能为空")
        if req.channel not in config.VALID_CHANNELS:
            raise FeatureAssemblyError(
                f"未知 channel={req.channel!r}，须属于 {config.VALID_CHANNELS}"
            )
        if not req.customer_id and not req.customer:
            raise FeatureAssemblyError(
                "必须提供 customer_id（已有客户）或 customer 画像字段（新客）"
            )

    # ------------------------------------------------------------ 画像

    def _resolve_customer(self, req: PredictRequest) -> tuple[pd.DataFrame, str, str]:
        """返回 (单行客户表, 模式, 用于历史查询的 customer_id)。"""
        cid = req.customer_id
        if cid and cid in self._known_customers:
            row = self._customer_index.loc[[cid]].reset_index()
            # 允许对已有客户做"假设分析"：请求里显式给的字段覆盖库中值
            for key, value in (req.customer or {}).items():
                if key in row.columns:
                    row.loc[:, key] = value
            return row, "existing_customer", cid

        # 新客：画像必须齐全
        missing = [f for f in REQUIRED_CUSTOMER_FIELDS if f not in (req.customer or {})]
        if missing:
            raise FeatureAssemblyError(
                f"新客需提供完整画像，缺少字段：{missing}\n"
                f"必填字段为：{list(REQUIRED_CUSTOMER_FIELDS)}"
            )
        data = {"customer_id": cid or "__NEW__"}
        data.update({f: req.customer[f] for f in REQUIRED_CUSTOMER_FIELDS})
        row = pd.DataFrame([data])
        row["register_date"] = pd.to_datetime(row["register_date"])
        row["aum"] = pd.to_numeric(row["aum"])
        row["has_app"] = pd.to_numeric(row["has_app"]).astype(int)
        # 新客在历史表中不存在，用一个不可能命中的哨兵 ID 查询，
        # 从而让历史特征自然落到冷启动默认值（而非写 if 分支特殊处理）
        return row, "new_customer", "__NO_HISTORY__"

    # ------------------------------------------------------------ 装配

    def assemble(self, req: PredictRequest) -> FeatureBundle:
        self._validate(req)
        as_of = pd.Timestamp(req.contact_date) if req.contact_date else self.default_as_of
        cust_row, mode, hist_key = self._resolve_customer(req)

        # 构造一条"触达记录"，字段与离线训练时完全同构
        contact = pd.DataFrame(
            [
                {
                    "contact_id": "__ONLINE__",
                    "customer_id": cust_row.loc[0, "customer_id"],
                    "product_id": req.product_id,
                    "channel": req.channel,
                    "contact_date": as_of,
                }
            ]
        )

        # 基础特征：直接复用离线函数
        base = pd.DataFrame(F.build_features(contact, cust_row, self.product))

        # 历史特征：走预建索引（新客的哨兵 ID 查不到 -> 各项为 0，
        # 平滑公式自然退化为先验，无需 if 分支特殊处理）
        hist_row = self.history.build_row(
            customer_id=hist_key,
            product_id=req.product_id,
            channel=req.channel,
            as_of=as_of,
        )
        history_available = bool(hist_row["cust_hist_cnt"] > 0)

        frame = base.copy()
        for col in self._history_columns:
            frame.loc[:, col] = hist_row[col]
        return FeatureBundle(
            frame=frame, mode=mode, as_of=as_of, history_available=history_available
        )
