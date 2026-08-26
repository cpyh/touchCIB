"""营销响应预测服务 —— 对外唯一入口。

用法（作为库）
--------------
    from partA1serving import ResponsePredictor, PredictRequest

    predictor = ResponsePredictor()          # 加载模型，约 1 次开销
    r = predictor.predict(PredictRequest(customer_id="C000001",
                                         product_id="P002",
                                         channel="manager"))
    print(r.probability, r.decision, r.reasons)

设计要点
--------
- **加载一次，复用多次**：模型与参考数据在构造时载入；单条推理约 2~3 ms。
- **输出不只是概率**：同时给出决策建议与可解释理由，否则运营看不懂分数。
  这是"能在工程上应用"与"只输出一个数"的区别。
- **预留 API 接入点**：`predict_dict()` 接受/返回纯 dict，
  HTTP 层只需做 JSON 序列化，无需理解内部结构。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import model_store
from .data_source import A1DataSource
from .feature_service import (
    FeatureAssemblyError,
    FeatureService,
    PredictRequest,
)

# 决策分档阈值。取自离线验证集的分位数，便于运营按人力预算圈选：
#   HIGH   ≈ 前 10%（对应 Lift@10% 口径，实测该组响应率约为整体的 3.8 倍）
#   MEDIUM ≈ 前 25%
#   LOW    其余
THRESHOLD_HIGH = 0.5763  # 验证集 p90
THRESHOLD_MEDIUM = 0.2777  # 验证集 p75

DECISION_LABELS = {
    "HIGH": "建议优先触达",
    "MEDIUM": "可纳入触达名单",
    "LOW": "暂不建议触达",
}


@dataclass
class PredictResult:
    """预测结果。字段设计面向运营可用，而非仅暴露模型输出。"""

    probability: float
    decision: str
    decision_label: str
    lift_vs_base: float  # 相对全体平均响应率的倍数
    # 请求回显：批量/排序场景下，结果必须自带上下文才能区分是哪一条
    customer_id: str
    product_id: str
    channel: str
    mode: str  # existing_customer / new_customer
    profile: str  # demo / full，便于核对结果来自哪套模型
    model_name: str  # lr / lgbm / lgbm_onehot
    as_of: str
    history_available: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResponsePredictor:
    """营销响应预测器。线程内复用同一实例即可。"""

    def __init__(
        self,
        profile: str = model_store.DEFAULT_PROFILE,
        model: str = "lr",
        models_root: str | None = None,
        data_source: A1DataSource | None = None,
    ) -> None:
        """加载指定 profile 的模型。

        Args:
            profile: "demo" —— 训练数据截止 2026-01-31，用于工程化演示；
                     该 profile 下 2026-02-01~2026-03-26 的数据模型从未见过，
                     可用其真实标签当场验证预测可信度。
                     "full" —— 全量 50000 条训练，仅用于生成提交物。
            model: 模型类型，如 "lr" / "lgbm" / "lgbm_onehot"。
                   同一 profile 下可并存多种模型，便于随时回滚。
            models_root: 模型根目录，默认包内 artifacts/。
        """
        self.profile = profile
        self.model_name = model
        self.pipeline, self.meta = model_store.load(profile, model, models_root)
        self.features = FeatureService(
            prior=self.meta.prior,
            default_as_of=self.meta.as_of_date,
            history_cutoff=self.meta.history_cutoff,
            data_source=data_source,
        )

    # ------------------------------------------------------------ 单条

    def predict(self, req: PredictRequest) -> PredictResult:
        bundle = self.features.assemble(req)
        beyond_cutoff = self.meta.history_cutoff is not None and bundle.as_of >= pd.Timestamp(
            self.meta.history_cutoff
        )
        frame = bundle.frame

        missing = [c for c in self.meta.feature_columns if c not in frame.columns]
        if missing:
            raise RuntimeError(
                f"特征装配缺少列：{missing}。通常意味着模型产物与当前特征代码不同步，请重新训练。"
            )
        # 严格按训练期的列顺序取值，顺序错会导致结果完全错误
        x = frame.loc[:, self.meta.feature_columns]
        prob = float(np.clip(self.pipeline.predict_proba(x)[:, 1][0], 0.0, 1.0))

        decision = (
            "HIGH" if prob >= THRESHOLD_HIGH else "MEDIUM" if prob >= THRESHOLD_MEDIUM else "LOW"
        )
        warnings: list[str] = []
        if beyond_cutoff:
            # 演示场景的正常用法：请求日期落在验证区间内。
            # 此时历史特征只到 cutoff，比训练期样本可见的历史略"旧"，
            # 明确告知调用方，避免把它误当成数据缺失。
            warnings.append(
                f"请求基准日 {bundle.as_of:%Y-%m-%d} 已超出模型的历史数据截止日 "
                f"{self.meta.history_cutoff}，历史类特征仅统计至截止日之前"
            )
        if not bundle.history_available:
            warnings.append("该客户无历史触达记录，历史类特征采用先验默认值，预测置信度较低")
        if bundle.mode == "new_customer":
            warnings.append("新客模式：画像由调用方提供，历史/持仓类特征均为冷启动值")

        return PredictResult(
            probability=round(prob, 6),
            decision=decision,
            decision_label=DECISION_LABELS[decision],
            lift_vs_base=round(prob / self.meta.prior, 3) if self.meta.prior > 0 else 0.0,
            customer_id=req.customer_id or "(new)",
            product_id=req.product_id,
            channel=req.channel,
            mode=bundle.mode,
            profile=self.profile,
            model_name=self.meta.model_name,
            as_of=f"{bundle.as_of:%Y-%m-%d}",
            history_available=bundle.history_available,
            reasons=self._explain(frame, top_n=5),
            warnings=warnings,
        )

    def predict_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        """dict 进 dict 出，供 HTTP / CLI 层直接使用。"""
        req = PredictRequest(
            product_id=payload.get("product_id", ""),
            channel=payload.get("channel", ""),
            customer_id=payload.get("customer_id"),
            contact_date=payload.get("contact_date"),
            customer=payload.get("customer", {}) or {},
        )
        return self.predict(req).to_dict()

    # ------------------------------------------------------------ 批量

    def predict_batch(self, requests: list[PredictRequest]) -> list[PredictResult]:
        """逐条装配后合并推理。

        注：此处按条装配是为了保证与单条完全一致的语义（含冷启动判定）；
        大批量离线打分请使用 `training/predict.py`，它走全量向量化路径。
        """
        return [self.predict(r) for r in requests]

    def rank_products(
        self,
        customer_id: str,
        channel: str,
        contact_date: str | None = None,
        top_n: int = 5,
    ) -> list[PredictResult]:
        """对全部 30 个产品打分并排序 —— 运营工作台的核心用法。"""
        results: list[tuple[float, PredictResult]] = []
        for pid in sorted(self.features._product_ids):
            r = self.predict(
                PredictRequest(
                    product_id=pid,
                    channel=channel,
                    customer_id=customer_id,
                    contact_date=contact_date,
                )
            )
            results.append((r.probability, r))
        results.sort(key=lambda t: -t[0])
        return [r for _, r in results[:top_n]]

    def best_channel(
        self, customer_id: str, product_id: str, contact_date: str | None = None
    ) -> list[PredictResult]:
        """比较四个渠道，给出最优触达方式。"""
        out: list[PredictResult] = []
        for ch in ("manager", "app_push", "call", "sms"):
            out.append(
                self.predict(
                    PredictRequest(
                        product_id=product_id,
                        channel=ch,
                        customer_id=customer_id,
                        contact_date=contact_date,
                    )
                )
            )
        out.sort(key=lambda r: -r.probability)
        return out

    # ------------------------------------------------------------ 可解释

    def _explain(self, frame: pd.DataFrame, top_n: int = 5) -> list[str]:
        """按 LR 系数 × 标准化后特征值，给出贡献最大的若干项。

        线性模型的贡献可精确分解为各项之和，这是选用 LR 的一个工程优势。
        """
        try:
            clf = self.pipeline.named_steps["clf"]
            if not hasattr(clf, "coef_"):
                # 树模型没有线性系数，改用全局特征重要性做近似解释。
                # 注意这是"模型整体关注什么"，而非"这一条为何得此分"，
                # 单条级别的精确归因需要 SHAP，此处不引入额外依赖。
                return self._explain_importance(top_n)
            pre = self.pipeline.named_steps["pre"]
            x = frame.loc[:, self.meta.feature_columns]
            z = np.asarray(pre.transform(x))[0]
            coefs = np.asarray(clf.coef_[0])
            names = list(pre.get_feature_names_out())
            contrib = coefs * z
            order = np.argsort(-np.abs(contrib))[:top_n]
            out = []
            for i in order:
                if abs(contrib[i]) < 1e-9:
                    continue
                sign = "提升" if contrib[i] > 0 else "降低"
                out.append(f"{names[i]}：{sign}响应概率（贡献 {contrib[i]:+.3f}）")
            return out
        except Exception as exc:  # pragma: no cover - 解释失败不应影响主流程
            return [f"（可解释信息生成失败：{exc}）"]

    def _explain_importance(self, top_n: int = 5) -> list[str]:
        """树模型的解释：按分裂增益给出模型整体最关注的特征。"""
        clf = self.pipeline.named_steps["clf"]
        booster = getattr(clf, "booster_", None)
        if booster is None:
            return ["（当前模型不支持导出特征重要性）"]
        names = list(booster.feature_name())
        # LightGBM 拿到的是编码后的矩阵，列名可能退化为 Column_0/1/2...
        # 这里用预处理器的输出名回填，否则解释信息对业务毫无意义。
        pre = self.pipeline.named_steps.get("pre")
        if pre is not None and all(n.startswith("Column_") for n in names[:3]):
            try:
                real = list(pre.get_feature_names_out())
                if len(real) == len(names):
                    names = real
            except (AttributeError, ValueError):
                pass
        gains = np.asarray(booster.feature_importance(importance_type="gain"), dtype=float)
        total = float(gains.sum()) or 1.0
        order = np.argsort(-gains)[:top_n]
        return [
            f"{names[i]}：模型整体增益占比 {gains[i] / total * 100:.2f}%（全局重要性）"
            for i in order
            if gains[i] > 0
        ]


__all__ = [
    "FeatureAssemblyError",
    "PredictRequest",
    "PredictResult",
    "ResponsePredictor",
]
