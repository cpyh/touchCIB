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
    FeatureBundle,
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


FEATURE_LABELS = {
    "channel": "触达渠道",
    "product_id": "当前产品",
    "product_type": "产品类型",
    "risk_level": "产品风险等级",
    "liquidity": "产品流动性",
    "age_group": "客户年龄段",
    "city": "客户所在城市",
    "occupation": "客户职业",
    "income_level": "客户收入等级",
    "risk_appetite": "客户风险偏好",
    "vip_level": "客户等级",
    "channel_x_vip": "渠道与客户等级匹配",
    "channel_x_has_app": "渠道与 App 状态匹配",
    "aum": "客户资产规模",
    "has_app": "App 使用状态",
    "expected_return": "产品预期收益",
    "volatility": "产品波动率",
    "min_invest": "产品起投金额",
    "duration_days": "产品期限",
    "income_ord": "收入等级",
    "vip_ord": "客户等级",
    "cust_risk_num": "客户风险承受力",
    "prod_risk_num": "产品风险等级",
    "product_age_days": "产品存续时间",
    "risk_gap": "客户与产品风险差",
    "abs_risk_gap": "风险等级匹配度",
    "is_risk_over": "产品风险是否越级",
    "aum_ge_min_invest": "可投资资产是否达到门槛",
    "log_aum_over_min_invest": "资产与起投金额匹配度",
    "sharpe": "产品风险收益比",
    "cust_hist_cnt": "客户历史触达次数",
    "cust_hist_resp": "客户历史响应次数",
    "cust_hist_rate": "客户历史响应率",
    "cust_ch_cnt": "该渠道历史触达次数",
    "cust_ch_rate": "该渠道历史响应率",
    "cust_ptype_cnt": "同类产品历史触达次数",
    "cust_ptype_rate": "同类产品历史响应率",
    "prod_hist_cnt": "产品历史触达次数",
    "prod_hist_rate": "产品历史响应率",
    "owns_this_product": "是否已持有当前产品",
    "hold_cnt": "当前持仓产品数",
    "hold_amount_log": "当前持仓规模",
    "owns_same_type": "是否持有同类产品",
    "consult_30d": "近 30 天咨询次数",
    "complaint_30d": "近 30 天投诉次数",
    "days_since_last_contact": "距上次触达天数",
}


@dataclass
class ExplanationFactor:
    """单次客户 × 产品 × 渠道预测的局部贡献因子。"""

    feature: str
    label: str
    direction: str
    contribution: float
    reason: str


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
    explanation_scope: str
    explanation_method: str
    local_factors: list[ExplanationFactor] = field(default_factory=list)
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

    def predict(self, req: PredictRequest, *, explain: bool = True) -> PredictResult:
        bundle = self.features.assemble(req)
        frame = bundle.frame

        missing = [c for c in self.meta.feature_columns if c not in frame.columns]
        if missing:
            raise RuntimeError(
                f"特征装配缺少列：{missing}。通常意味着模型产物与当前特征代码不同步，请重新训练。"
            )
        # 严格按训练期的列顺序取值，顺序错会导致结果完全错误
        x = frame.loc[:, self.meta.feature_columns]
        prob = float(np.clip(self.pipeline.predict_proba(x)[:, 1][0], 0.0, 1.0))

        return self._result(req, bundle, prob, explain=explain)

    def _result(self, req, bundle, prob: float, *, explain: bool) -> PredictResult:
        """把已装配特征和概率转为统一服务契约。"""
        beyond_cutoff = self.meta.history_cutoff is not None and bundle.as_of >= pd.Timestamp(
            self.meta.history_cutoff
        )

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

        local_factors, explanation_method = (
            self._explain_factors(bundle.frame, top_n=5)
            if explain
            else ([], "not_requested")
        )

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
            explanation_scope="customer_product_channel",
            explanation_method=explanation_method,
            local_factors=local_factors,
            reasons=[factor.reason for factor in local_factors],
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

    def predict_batch(
        self,
        requests: list[PredictRequest],
        *,
        explain: bool = False,
    ) -> list[PredictResult]:
        """逐条装配特征，但一次向量化模型推理，与单条口径一致。"""
        if not requests:
            return []
        feature_batch = self.features.assemble_batch(requests)
        merged = feature_batch.frame
        missing = [column for column in self.meta.feature_columns if column not in merged.columns]
        if missing:
            raise RuntimeError(
                f"特征装配缺少列：{missing}。通常意味着模型产物与当前特征代码不同步，请重新训练。"
            )
        probabilities = np.clip(
            self.pipeline.predict_proba(merged.loc[:, self.meta.feature_columns])[:, 1],
            0.0,
            1.0,
        )
        empty_frame = merged.iloc[0:0]
        results: list[PredictResult] = []
        for index, (request, probability) in enumerate(
            zip(requests, probabilities, strict=True)
        ):
            bundle = FeatureBundle(
                frame=(
                    merged.iloc[[index]].reset_index(drop=True)
                    if explain
                    else empty_frame
                ),
                mode=feature_batch.modes[index],
                as_of=feature_batch.as_of_values[index],
                history_available=feature_batch.history_available[index],
            )
            results.append(
                self._result(
                    request,
                    bundle,
                    float(probability),
                    explain=explain,
                )
            )
        return results

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

    @staticmethod
    def _feature_label(name: str) -> str:
        """把编码后的模型列名翻译成客户经理可读的业务概念。"""
        for feature in sorted(FEATURE_LABELS, key=len, reverse=True):
            if name == feature or name.startswith(f"{feature}_"):
                suffix = name[len(feature) :].lstrip("_")
                return (
                    f"{FEATURE_LABELS[feature]} · {suffix}"
                    if suffix
                    else FEATURE_LABELS[feature]
                )
        return name

    @classmethod
    def _factor(cls, name: str, contribution: float) -> ExplanationFactor:
        direction = "positive" if contribution > 0 else "negative"
        label = cls._feature_label(name)
        verb = "提升" if contribution > 0 else "降低"
        reason = f"{label}：{verb}本次响应倾向（局部贡献 {contribution:+.3f}）"
        return ExplanationFactor(
            feature=name,
            label=label,
            direction=direction,
            contribution=round(float(contribution), 6),
            reason=reason,
        )

    def _explain_factors(
        self, frame: pd.DataFrame, top_n: int = 5
    ) -> tuple[list[ExplanationFactor], str]:
        """返回当前请求的局部贡献，而不是模型的全局重要性。

        LR 使用 ``系数 × 标准化特征值``；LightGBM 使用内置 TreeSHAP
        ``pred_contrib``。两者都只解释当前客户、产品和渠道这一次预测。
        """
        try:
            clf = self.pipeline.named_steps["clf"]
            x = frame.loc[:, self.meta.feature_columns]
            if hasattr(clf, "coef_"):
                pre = self.pipeline.named_steps["pre"]
                z = np.asarray(pre.transform(x))[0]
                names = list(pre.get_feature_names_out())
                contrib = np.asarray(clf.coef_[0]) * z
                method = "linear_contribution"
            else:
                booster = getattr(clf, "booster_", None)
                if booster is None:
                    return [], "unavailable"
                transformed: Any = x
                for _, step in self.pipeline.steps[:-1]:
                    transformed = step.transform(transformed)
                if "pre" in self.pipeline.named_steps:
                    names = list(
                        self.pipeline.named_steps["pre"].get_feature_names_out()
                    )
                elif isinstance(transformed, pd.DataFrame):
                    names = list(transformed.columns)
                else:
                    names = list(booster.feature_name())
                # 最后一列是 expected value，不属于任何业务特征。
                contrib = np.asarray(
                    booster.predict(transformed, pred_contrib=True)
                )[0][:-1]
                method = "tree_shap"

            if len(names) != len(contrib):
                return [], "unavailable"
            order = np.argsort(-np.abs(contrib))[:top_n]
            return (
                [
                    self._factor(names[i], float(contrib[i]))
                    for i in order
                    if abs(contrib[i]) >= 1e-9
                ],
                method,
            )
        except Exception as exc:  # pragma: no cover - 解释失败不应影响主流程
            return [
                ExplanationFactor(
                    feature="explanation_error",
                    label="局部解释暂不可用",
                    direction="neutral",
                    contribution=0.0,
                    reason=f"局部解释生成失败：{exc}",
                )
            ], "unavailable"

__all__ = [
    "FeatureAssemblyError",
    "PredictRequest",
    "PredictResult",
    "ResponsePredictor",
]
