"""生成 A1 提交文件 `partA_prediction.csv`。

与验证阶段（training/pipeline.py）的区别
----------------------------------------
验证阶段按时间切分，只用训练段拟合，目的是**估计**线上表现。
本脚本用于**产出提交**，因此：
  1. 用全部 50000 条 t_campaign 拟合（不再留出验证段），充分利用数据；
  2. 测试集的历史统计特征全部来自训练集（推理模式），
     测试日 2026-04-15 晚于所有训练数据，故等价于使用全部训练历史；
  3. 平滑先验统一取自训练集，保证训练/推理口径一致。

输出精度
--------
概率保留 6 位小数。题面说明后台按 **3 位小数去重**扫描 F1 阈值，
若输出精度过低（如 2 位小数）会让候选阈值锐减到约 101 个，
搜索变粗、F1 吃亏。校验器会对此给出提醒。

用法
----
    python -m partA1serving.training.predict
    python -m partA1serving.training.predict --no-history   # 消融：仅用基础特征
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .. import config
from .. import estimators as M
from .. import features_a1 as F
from .. import features_history as H
from .pipeline import build_pipeline, get_all_feature_columns


def generate(
    use_history: bool = True, verbose: bool = True, model: str = M.DEFAULT_MODEL
) -> pd.DataFrame:
    """在全量训练集上拟合，对测试集输出响应概率。"""
    customer, product = F.load_base_tables()
    train_raw = F.load_train_contacts()
    test_raw = F.load_test_contacts()

    if verbose:
        print("=" * 66)
        print(f"生成 A1 提交文件 partA_prediction.csv | 模型={model}")
        print(f"  {M.describe(model)}")
        print("=" * 66)
        print(f"\n[数据] 训练 {len(train_raw)} 条  测试 {len(test_raw)} 条")
        print(
            f"       训练期 {train_raw['contact_date'].min():%Y-%m-%d}"
            f" ~ {train_raw['contact_date'].max():%Y-%m-%d}"
        )
        print(f"       测试日 {test_raw['contact_date'].min():%Y-%m-%d}（晚于全部训练数据）")

    # ---------------- 基础特征：train / test 共用同一函数
    train = pd.DataFrame(F.build_features(train_raw, customer, product))
    test = pd.DataFrame(F.build_features(test_raw, customer, product))

    # ---------------- 历史特征
    if use_history:
        holding = H.load_holding()
        events = H.load_events()
        # 先验统一取自训练集，训练与推理保持同一口径
        prior = float(train_raw["responded"].mean())

        hist_train = H.build_history_features(
            train_raw, holding, events, label_col="responded", prior=prior
        )
        # 推理模式：测试集自身无标签，历史全部来自训练集
        hist_test = H.build_history_features(
            test_raw,
            holding,
            events,
            label_col=None,
            history_source=train_raw,
            prior=prior,
        )
        train = train.merge(hist_train, on="contact_id", how="left")
        test = test.merge(hist_test, on="contact_id", how="left")

        if verbose:
            print(f"\n[历史特征] 平滑先验 prior = {prior:.6f}（取自训练集）")
            print("       测试集历史来自全量训练集（推理模式）")
            print(
                "       注：t_event 数据截止 2026-03-27，测试日 30 天窗口后段无事件，"
                "\n           故 consult_30d/complaint_30d 在测试集上偏低，属数据边界而非缺陷"
            )

    feat_cols = get_all_feature_columns(use_history)

    # ---------------- 一致性自检
    missing_cols = [c for c in feat_cols if c not in test.columns]
    if missing_cols:
        raise ValueError(f"测试集缺少特征列：{missing_cols}")
    n_na_train = int(train[feat_cols].isna().sum().sum())
    n_na_test = int(test[feat_cols].isna().sum().sum())
    if n_na_train or n_na_test:
        raise ValueError(f"存在缺失值：train={n_na_train}, test={n_na_test}")

    if verbose:
        print("\n[自检]")
        print(f"  特征列数              : {len(feat_cols)}")
        print("  train/test 特征列一致 : True")
        print(f"  缺失值                : train={n_na_train}, test={n_na_test}")
        print(f"  训练集正例率          : {train['responded'].mean():.6f}")

    # ---------------- 全量拟合
    x_train = train.loc[:, feat_cols]
    y_train = np.asarray(train["responded"])
    pipe = build_pipeline(use_history, model)
    pipe.fit(x_train, y_train)

    if verbose:
        n_encoded = M.encoded_width(pipe, x_train.iloc[:1])
        print(f"  编码后维度            : {len(feat_cols)} -> {n_encoded} 列")

    # ---------------- 推理
    prob = pipe.predict_proba(test.loc[:, feat_cols])[:, 1]
    # 数值兜底：确保严格落在 [0, 1]，避免极端浮点导致格式判 0
    prob = np.clip(prob, 0.0, 1.0)

    out = pd.DataFrame(
        {
            "contact_id": test["contact_id"].to_numpy(),
            "response_prob": np.round(prob, 6),
        }
    )

    if verbose:
        print("\n[预测分布]")
        print(f"  均值   : {prob.mean():.6f}（训练集正例率 {y_train.mean():.6f}）")
        print(f"  区间   : [{prob.min():.6f}, {prob.max():.6f}]")
        qs = np.percentile(prob, [10, 25, 50, 75, 90])
        print("  分位数 : p10={:.4f} p25={:.4f} p50={:.4f} p75={:.4f} p90={:.4f}".format(*qs))
        n_distinct3 = len(np.unique(np.round(prob, 3)))
        print(f"  按 3 位小数去重的不同值: {n_distinct3}（后台据此扫描 F1 阈值，越多越好）")

    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 partA_prediction.csv")
    ap.add_argument(
        "--out",
        default=os.path.join(config.SUBMISSION_DIR, config.FILE_PREDICTION),
        help="输出路径，默认 submission/partA_prediction.csv",
    )
    ap.add_argument("--no-history", action="store_true", help="不使用历史统计特征（消融用）")
    ap.add_argument(
        "--model",
        default=M.DEFAULT_MODEL,
        choices=M.list_models(),
        help="模型类型，默认 lr（与基线一致）",
    )
    args = ap.parse_args(argv)

    out = generate(use_history=not args.no_history, model=args.model)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out.to_csv(args.out, index=False)
    size_mib = os.path.getsize(args.out) / config.MIB
    print(f"\n已写出 {args.out}")
    print(f"  行数 {len(out)}  大小 {size_mib:.3f} MiB（上限 5 MiB）")
    print("\n请运行校验器确认格式：")
    print("  .venv/bin/python submission/src/validate_submission.py --part A1 -v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
