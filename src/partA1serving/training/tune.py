"""LightGBM 超参调优：在训练段内部用时序交叉验证。

为什么不能直接用验证集调参
--------------------------
验证集（2026-02-01 ~ 2026-03-26）是我们估计线上表现的唯一依据。
若用它挑选超参，等于让超参"见过"验证集，报告的 AUC 会系统性虚高，
线上必然回落。LR 因为不调参没有这个问题，LightGBM 超参多，必须隔离。

因此调参只在**训练段（< 2026-02-01）内部**进行，验证集全程不参与，
保持完全无偏。

为什么用时序切分而不是随机 K 折
-------------------------------
测试集时间上晚于全部训练数据，随机 K 折会让"未来"数据进入训练折，
高估模型能力。这里按时间把训练段切成若干折，每折都用较早数据训练、
较晚数据验证，与线上"用过去预测未来"的方向一致。

历史特征的处理
--------------
每一折都**单独重算**历史特征：训练部分用自身逐行 as-of 展开，
验证部分只能引用该折训练部分的历史。若图省事在全训练段上算一次再切分，
折内验证部分就会通过历史特征间接看到未来标签，调参结论失真。

用法
----
    python -m partA1serving.training.tune --model lgbm
    python -m partA1serving.training.tune --model lgbm_onehot --n-splits 4
    python -m partA1serving.training.tune --model lgbm --quick   # 小网格快速验证
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time

import numpy as np
import pandas as pd

from .. import config
from .. import estimators as M
from .. import features_a1 as F
from .. import features_history as H
from .pipeline import DEFAULT_CUT, evaluate, get_all_feature_columns


# 完整搜索网格。逐维取值都围绕"抑制过拟合"展开：
# 5 万行小样本 + 46 特征，LightGBM 极易记住训练集。
# 网格围绕"抑制过拟合"设计。快速粗筛已显示强正则方向更优
# （num_leaves=15 优于 31、reg_lambda=5 优于 1），故聚焦该区域，
# 避免 200+ 组合带来的无谓耗时。
GRID: dict[str, list] = {
    "n_estimators": [200, 300, 500],
    "learning_rate": [0.03, 0.05],
    "num_leaves": [7, 15, 31],
    "min_child_samples": [50, 100],
    "colsample_bytree": [0.8],
    "reg_lambda": [5.0, 20.0],
}

# 快速网格：用于验证流程可跑通，或时间紧张时的粗筛
QUICK_GRID: dict[str, list] = {
    "n_estimators": [300, 600],
    "learning_rate": [0.05],
    "num_leaves": [15, 31],
    "min_child_samples": [50],
    "colsample_bytree": [0.8],
    "reg_lambda": [1.0, 5.0],
}


def time_series_folds(
    dates: pd.Series, n_splits: int = 3, min_train_ratio: float = 0.5
) -> list[tuple[np.ndarray, np.ndarray]]:
    """按时间把训练段切成 n_splits 折（扩展窗口）。

    第 i 折：训练 = 最早到某时点，验证 = 其后一段。
    训练部分随折数递增而扩大，验证段长度大致相等。
    """
    order = np.argsort(dates.to_numpy(), kind="stable")
    n = len(order)
    start = int(n * min_train_ratio)
    step = (n - start) // n_splits
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(n_splits):
        tr_end = start + i * step
        va_end = n if i == n_splits - 1 else start + (i + 1) * step
        if tr_end <= 0 or va_end <= tr_end:
            continue
        folds.append((order[:tr_end], order[tr_end:va_end]))
    return folds


def _fold_matrices(
    contacts: pd.DataFrame,
    base: pd.DataFrame,
    holding: pd.DataFrame,
    events: pd.DataFrame,
    tr_idx: np.ndarray,
    va_idx: np.ndarray,
    feat_cols: list[str],
) -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame, np.ndarray]:
    """为单折构造特征矩阵，历史特征按折内边界重算（避免折内穿越）。"""
    tr_raw = contacts.iloc[tr_idx].reset_index(drop=True)
    va_raw = contacts.iloc[va_idx].reset_index(drop=True)
    prior = float(tr_raw["responded"].mean())

    h_tr = H.build_history_features(tr_raw, holding, events, label_col="responded", prior=prior)
    h_va = H.build_history_features(
        va_raw, holding, events, label_col=None, history_source=tr_raw, prior=prior
    )
    tr = base.merge(h_tr, on="contact_id", how="inner")
    va = base.merge(h_va, on="contact_id", how="inner")
    return (
        tr.loc[:, feat_cols],
        np.asarray(tr["responded"]),
        va.loc[:, feat_cols],
        np.asarray(va["responded"]),
    )


def run(
    model: str = "lgbm",
    n_splits: int = 3,
    quick: bool = False,
    cut: str = DEFAULT_CUT,
    out_path: str | None = None,
) -> dict:
    customer, product = F.load_base_tables()
    contacts_all = F.load_train_contacts()
    holding = H.load_holding()
    events = H.load_events()

    cut_ts = pd.Timestamp(cut)
    # 只用训练段调参，验证段全程不参与
    contacts = (
        contacts_all.loc[contacts_all["contact_date"] < cut_ts]
        .sort_values(["contact_date", "contact_id"])
        .reset_index(drop=True)
    )
    base = pd.DataFrame(F.build_features(contacts, customer, product))
    feat_cols = get_all_feature_columns(True)

    grid = QUICK_GRID if quick else GRID
    combos = [dict(zip(grid, v, strict=True)) for v in itertools.product(*grid.values())]

    print("=" * 70)
    print(f"LightGBM 超参调优 | 模型={model}")
    print("=" * 70)
    print(f"\n[数据] 训练段 {len(contacts)} 条（< {cut}），验证段不参与调参")
    print(f"[切分] 时序 {n_splits} 折（扩展窗口）")
    folds = time_series_folds(contacts["contact_date"], n_splits)
    for i, (tr_i, va_i) in enumerate(folds, start=1):
        print(
            f"  折{i}: 训练 {len(tr_i):>6} 条 "
            f"({contacts['contact_date'].iloc[tr_i].max():%Y-%m-%d} 前) / "
            f"验证 {len(va_i):>6} 条"
        )
    print(f"[网格] {len(combos)} 组超参 × {len(folds)} 折 = {len(combos) * len(folds)} 次训练")

    # 各折矩阵只算一次，供全部超参组合复用（历史特征重算是主要开销）
    print("\n[准备] 预计算各折特征矩阵 ...")
    t0 = time.time()
    fold_data = [
        _fold_matrices(contacts, base, holding, events, tr_i, va_i, feat_cols)
        for tr_i, va_i in folds
    ]
    print(f"       完成，耗时 {time.time() - t0:.1f}s")

    print("\n[搜索]")
    results: list[tuple[float, float, dict]] = []
    t0 = time.time()
    for k, params in enumerate(combos, start=1):
        aucs: list[float] = []
        for x_tr, y_tr, x_va, y_va in fold_data:
            pipe = M.build_model(model, use_history=True, **params)
            pipe.fit(x_tr, y_tr)
            aucs.append(float(evaluate(y_va, pipe.predict_proba(x_va)[:, 1]).auc))
        mean_auc, std_auc = float(np.mean(aucs)), float(np.std(aucs))
        results.append((mean_auc, std_auc, params))
        if k % max(1, len(combos) // 10) == 0 or k == len(combos):
            best = max(results, key=lambda t: t[0])
            print(
                f"  {k:>3}/{len(combos)}  当前最优 CV-AUC={best[0]:.6f}  "
                f"（已用 {time.time() - t0:.0f}s）"
            )

    results.sort(key=lambda t: -t[0])
    print(f"\n[结果] 搜索耗时 {time.time() - t0:.1f}s")
    print("\n  Top 5 超参组合（按折间平均 CV-AUC）")
    for mean_auc, std_auc, params in results[:5]:
        compact = ", ".join(f"{k}={v}" for k, v in params.items())
        print(f"    CV-AUC={mean_auc:.6f} ±{std_auc:.6f}  {compact}")

    best_auc, best_std, best_params = results[0]
    print(f"\n  最优：CV-AUC={best_auc:.6f} ±{best_std:.6f}")
    print(f"        {json.dumps(best_params, ensure_ascii=False)}")

    payload = {
        "model": model,
        "cut": cut,
        "n_splits": n_splits,
        "grid_size": len(combos),
        "random_state": config.RANDOM_STATE,
        "best_params": best_params,
        "best_cv_auc": round(best_auc, 6),
        "best_cv_std": round(best_std, 6),
        "top5": [
            {"cv_auc": round(a, 6), "cv_std": round(s, 6), "params": p} for a, s, p in results[:5]
        ],
    }
    path = out_path or os.path.join(config.MODELS_DIR, f"tuning_{model}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\n已写出调参结果 -> {path}")
    print("\n下一步：用最优超参训练并评估（验证段仍为无偏估计）")
    print(f"  python -m partA1serving.training.pipeline --model {model}")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LightGBM 时序 CV 调参")
    ap.add_argument(
        "--model",
        default="lgbm",
        choices=[m for m in M.list_models() if m.startswith("lgbm")],
        help="要调参的模型，默认 lgbm",
    )
    ap.add_argument("--n-splits", type=int, default=3, help="时序折数，默认 3")
    ap.add_argument("--quick", action="store_true", help="使用小网格快速验证流程")
    ap.add_argument("--cut", default=DEFAULT_CUT, help=f"训练/验证切分点，默认 {DEFAULT_CUT}")
    ap.add_argument("--out", default=None, help="调参结果输出路径")
    args = ap.parse_args(argv)

    run(
        model=args.model,
        n_splits=args.n_splits,
        quick=args.quick,
        cut=args.cut,
        out_path=args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
