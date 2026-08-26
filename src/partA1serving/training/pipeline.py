"""A1 营销响应预测 —— 训练/评估流水线（模型无关）。

目的
----
用最简单的线性模型跑通「拼表 → 特征 → 训练 → 评估」全链路，
并对标题面给出的官方基线 **AUC ≈ 0.82**，以此校准整条流水线是否正确。
同时承载评分口径（Metrics）、特征列聚合（get_all_feature_columns）等
被训练/预测/调参/回放复用的公共逻辑。

评估方式
--------
按时间切分留出：训练 < 2026-02-01，验证 >= 2026-02-01。
理由：测试集 contact_date 为 2026-04-15，位于全部训练数据之后，
     时间切分能模拟"用过去预测未来"的真实场景。

评分口径与题面一致
------------------
- AUC：0.79 -> 6.8 分，0.85 -> 17 分（线性插值，地板 3.4）
- F1 ：后台扫描全部预测值（按 3 位小数去重）取最高 F1；0.50 -> 2.8 分，0.615 -> 7 分
- Lift@10%：按概率降序取前 10%，该组响应率 / 全体响应率；2.6 -> 2.4 分，3.3 -> 6 分

用法
----
    python -m partA1serving.training.pipeline
    python -m partA1serving.training.pipeline --cut 2026-01-01
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.pipeline import Pipeline

from .. import estimators as M
from .. import features_a1 as F
from .. import features_history as H


DEFAULT_CUT = "2026-02-01"


# ================================================================ 评分口径


@dataclass
class Metrics:
    auc: float
    f1: float
    f1_threshold: float
    lift10: float

    @property
    def auc_score(self) -> float:
        return _interp_score(self.auc, lo=0.79, hi=0.85, lo_s=6.8, hi_s=17.0, floor=3.4)

    @property
    def f1_score_pts(self) -> float:
        return _interp_score(self.f1, lo=0.50, hi=0.615, lo_s=2.8, hi_s=7.0, floor=1.4)

    @property
    def lift_score(self) -> float:
        return _interp_score(self.lift10, lo=2.6, hi=3.3, lo_s=2.4, hi_s=6.0, floor=1.2)

    @property
    def total_score(self) -> float:
        return self.auc_score + self.f1_score_pts + self.lift_score


def _interp_score(
    value: float, lo: float, hi: float, lo_s: float, hi_s: float, floor: float
) -> float:
    """按题面锚点线性插值，并夹在 [floor, hi_s] 内。"""
    if value <= lo:
        # 低锚点以下按 (0, floor) -> (lo, lo_s) 继续线性插值
        score = floor + (value / lo) * (lo_s - floor) if lo > 0 else floor
    else:
        score = lo_s + (value - lo) / (hi - lo) * (hi_s - lo_s)
    return float(min(max(score, floor), hi_s))


def best_f1(y_true: np.ndarray, y_prob: np.ndarray) -> tuple[float, float]:
    """按后台口径扫描阈值：全部预测值按 3 位小数去重作为候选，取最高 F1。"""
    candidates = np.unique(np.round(y_prob, 3))
    best_val, best_thr = 0.0, 0.5
    for thr in candidates:
        pred = (y_prob >= thr).astype(int)
        # sklearn 运行时接受数值 0；其类型 stub 误标为 str，故此处忽略类型检查
        val = f1_score(y_true, pred, zero_division=0)  # pyright: ignore[reportArgumentType]
        if val > best_val:
            best_val, best_thr = float(val), float(thr)
    return best_val, best_thr


def lift_at_k(y_true: np.ndarray, y_prob: np.ndarray, k: float = 0.10) -> float:
    """按概率降序取前 k 比例，该组实际响应率 / 全体响应率。"""
    n_top = max(1, round(len(y_prob) * k))
    order = np.argsort(-y_prob, kind="stable")
    top_rate = float(y_true[order[:n_top]].mean())
    base_rate = float(y_true.mean())
    return top_rate / base_rate if base_rate > 0 else 0.0


def evaluate(y_true: np.ndarray, y_prob: np.ndarray) -> Metrics:
    f1_val, f1_thr = best_f1(y_true, y_prob)
    return Metrics(
        auc=float(roc_auc_score(y_true, y_prob)),
        f1=f1_val,
        f1_threshold=f1_thr,
        lift10=lift_at_k(y_true, y_prob),
    )


# ================================================================ 模型


def build_pipeline(use_history: bool = True, model: str = M.DEFAULT_MODEL) -> Pipeline:
    """构建模型 Pipeline。

    默认 model="lr"，与引入多模型机制之前的行为逐位一致
    （`tests/test_models.py` 有断言校验）。传入其他名称可切换模型，
    可选值见 `estimators.list_models()`。
    """
    return M.build_model(model, use_history=use_history)


def get_all_feature_columns(use_history: bool = True) -> list[str]:
    cols = F.get_feature_columns()
    if use_history:
        cols = cols + H.get_history_columns()
    return cols


# ================================================================ 主流程


def run(
    cut: str = DEFAULT_CUT,
    verbose: bool = True,
    use_history: bool = True,
    model: str = M.DEFAULT_MODEL,
) -> Metrics:
    customer, product = F.load_base_tables()
    contacts = F.load_train_contacts()

    if verbose:
        print("=" * 66)
        print(
            "A1 LogisticRegression 基线"
            + ("（含历史统计特征）" if use_history else "（仅基础特征）")
        )
        print("=" * 66)
        print(f"\n[特征清单]\n{F.describe_features()}")
        if use_history:
            print(f"\n{H.describe_history_features()}")

    # ---------------- 拼表
    data = pd.DataFrame(F.build_features(contacts, customer, product))

    cut_ts = pd.Timestamp(cut)
    train_mask = data["contact_date"] < cut_ts

    if use_history:
        # 训练段：历史来自训练段自身，逐行 as-of 展开
        train_raw = contacts.loc[np.asarray(train_mask)].reset_index(drop=True)
        valid_raw = contacts.loc[~np.asarray(train_mask)].reset_index(drop=True)

        holding = H.load_holding()
        events = H.load_events()
        # 先验统一取训练段，避免验证段信息渗入
        prior = float(train_raw["responded"].mean())

        hist_train = H.build_history_features(
            train_raw, holding, events, label_col="responded", prior=prior
        )
        # 验证段：历史只能来自训练段（与线上推理一致，验证段自身标签不可见）
        hist_valid = H.build_history_features(
            valid_raw,
            holding,
            events,
            label_col=None,
            history_source=train_raw,
            prior=prior,
        )
        hist_all = pd.concat([hist_train, hist_valid], ignore_index=True)
        data = data.merge(hist_all, on="contact_id", how="left")

    feat_cols = get_all_feature_columns(use_history)

    if verbose:
        print("\n[拼表自检]")
        print(f"  触达记录行数        : {len(contacts)}")
        print(f"  拼表后行数          : {len(data)}  （应相等，否则右表主键重复）")
        n_missing = int(data[feat_cols].isna().sum().sum())
        print(f"  特征列缺失值总数    : {n_missing}")
        print(f"  特征列数            : {len(feat_cols)}")

    # ---------------- 按时间切分
    train = data.loc[data["contact_date"] < cut_ts]
    valid = data.loc[data["contact_date"] >= cut_ts]

    x_train = train.loc[:, feat_cols]
    x_valid = valid.loc[:, feat_cols]
    y_train = np.asarray(train["responded"])
    y_valid = np.asarray(valid["responded"])

    if verbose:
        tr_lo, tr_hi = train["contact_date"].min(), train["contact_date"].max()
        va_lo, va_hi = valid["contact_date"].min(), valid["contact_date"].max()
        print(f"\n[时间切分] 切分点 {cut}")
        print(
            f"  训练集: {len(train):>6} 条  正例率 {y_train.mean():.4f}  "
            f"({tr_lo:%Y-%m-%d} ~ {tr_hi:%Y-%m-%d})"
        )
        print(
            f"  验证集: {len(valid):>6} 条  正例率 {y_valid.mean():.4f}  "
            f"({va_lo:%Y-%m-%d} ~ {va_hi:%Y-%m-%d})"
        )
        if use_history:
            print("  注：验证段的历史统计只取自训练段，与线上推理口径一致")

    # ---------------- 训练
    pipe = build_pipeline(use_history, model)
    pipe.fit(x_train, y_train)

    n_encoded = M.encoded_width(pipe, x_train.iloc[:1])
    if verbose:
        print(f"\n[编码后维度] {len(feat_cols)} 个原始特征 -> {n_encoded} 列")

    # ---------------- 评估
    prob_valid = pipe.predict_proba(x_valid)[:, 1]
    m = evaluate(y_valid, prob_valid)

    if verbose:
        print("\n[验证集指标]（题面口径）")
        print(f"  AUC        = {m.auc:.4f}   -> {m.auc_score:5.2f} / 17 分")
        print(
            f"  F1(最优)   = {m.f1:.4f}   -> {m.f1_score_pts:5.2f} /  7 分"
            f"   (最优阈值 {m.f1_threshold:.3f})"
        )
        print(f"  Lift@10%   = {m.lift10:.4f}   -> {m.lift_score:5.2f} /  6 分")
        print(f"  {'合计':<10} {'':8}    -> {m.total_score:5.2f} / 30 分")

        # 校准判断：题面称官方 LR 基线 AUC 约 0.82
        print("\n[基线校准]")
        if 0.80 <= m.auc <= 0.84:
            print(f"  AUC {m.auc:.4f} 落在 0.80~0.84，与题面官方 LR 基线 0.82 吻合，流水线正确。")
        elif m.auc > 0.90:
            print(f"  ⚠ AUC {m.auc:.4f} 异常偏高，检查是否存在标签泄漏（如 responded 混入特征）。")
        elif m.auc < 0.75:
            print(f"  ⚠ AUC {m.auc:.4f} 明显偏低，检查拼表或编码是否有误。")
        else:
            print(f"  AUC {m.auc:.4f} 与官方基线 0.82 略有偏差，属可接受范围。")

        if model == "lr":
            _print_top_coefficients(pipe, top_n=15)
        else:
            _print_top_importances(pipe, top_n=15)

    return m


def _print_top_coefficients(pipe: Pipeline, top_n: int = 15) -> None:
    """打印系数绝对值最大的特征，用于确认模型学到的方向符合业务直觉。"""
    pre = pipe.named_steps["pre"]
    clf = pipe.named_steps["clf"]
    names = list(pre.get_feature_names_out())
    coefs = clf.coef_[0]
    order = np.argsort(-np.abs(coefs))[:top_n]

    print(f"\n[系数最大的 {top_n} 个特征]（正=促进响应，负=抑制响应）")
    for i in order:
        print(f"  {coefs[i]:+8.4f}  {names[i]}")


def _print_top_importances(pipe: Pipeline, top_n: int = 15) -> None:
    """打印树模型的特征重要性（按增益），用于确认模型关注点符合业务直觉。"""
    clf = pipe.named_steps["clf"]
    booster = getattr(clf, "booster_", None)
    if booster is None:
        print("\n[特征重要性] 当前模型不支持导出重要性")
        return
    names = list(booster.feature_name())
    gains = np.asarray(booster.feature_importance(importance_type="gain"), dtype=float)
    total = gains.sum() or 1.0
    order = np.argsort(-gains)[:top_n]
    print(f"\n[特征重要性 Top {top_n}]（按分裂增益占比）")
    for i in order:
        print(f"  {gains[i] / total * 100:6.2f}%  {names[i]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A1 LogisticRegression 基线")
    ap.add_argument("--cut", default=DEFAULT_CUT, help=f"时间切分点，默认 {DEFAULT_CUT}")
    ap.add_argument(
        "--model",
        default=M.DEFAULT_MODEL,
        choices=M.list_models(),
        help="模型类型，默认 lr（与基线行为一致）",
    )
    ap.add_argument("-q", "--quiet", action="store_true", help="只输出最终指标")
    ap.add_argument(
        "--no-history",
        action="store_true",
        help="不使用历史统计特征（用于消融对比第 2 步的基础特征结果）",
    )
    args = ap.parse_args(argv)

    m = run(
        cut=args.cut,
        verbose=not args.quiet,
        use_history=not args.no_history,
        model=args.model,
    )
    if args.quiet:
        print(
            f"AUC={m.auc:.4f} F1={m.f1:.4f} Lift@10%={m.lift10:.4f} 预估得分={m.total_score:.2f}/30"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
