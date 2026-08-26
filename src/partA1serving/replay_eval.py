"""演示模型的线上回放验证。

用途
----
工程化演示最需要回答的问题是：**"这个服务给出的分数可信吗？"**

本脚本用 demo 模型（训练数据截止 2026-01-31）逐条回放
2026-02-01 ~ 2026-03-26 的 7358 条真实触达记录，全部走**在线服务接口**
（而非离线批量路径），再用这些记录的真实标签计算 AUC / F1 / Lift@10%。

由于这批数据模型从未见过，指标是无偏的；且调用路径与生产完全一致，
因此可以同时证明两件事：
  1. 模型的预测能力（指标本身）；
  2. 在线服务的正确性（在线结果与离线批量逐位一致）。

用法
----
    python -m partA1serving.replay_eval                  # 全量 7358 条
    python -m partA1serving.replay_eval --limit 500      # 抽样快速验证
    python -m partA1serving.replay_eval --check-offline  # 额外比对离线
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

from . import features_a1 as F
from . import features_history as H
from . import model_store
from .feature_service import PredictRequest
from .predictor import ResponsePredictor
from .training.pipeline import evaluate


def run(limit: int | None = None, check_offline: bool = False) -> int:
    predictor = ResponsePredictor(profile="demo")
    meta = predictor.meta

    if meta.train_cutoff is None:
        print("错误：当前模型没有训练截止日，无法做无偏回放验证。", file=sys.stderr)
        print("      请使用 --profile demo 训练的模型。", file=sys.stderr)
        return 2

    cutoff = pd.Timestamp(meta.train_cutoff)
    contacts = F.load_train_contacts()
    holdout = contacts.loc[contacts["contact_date"] >= cutoff].reset_index(drop=True)

    print("=" * 68)
    print("演示模型线上回放验证")
    print("=" * 68)
    print(f"\n[模型] profile={meta.profile}")
    print(f"       训练区间   {meta.train_range}（{meta.n_train_rows} 条）")
    print(f"       训练截止   {meta.train_cutoff}（严格小于）")
    print(f"       as-of 默认 {meta.as_of_date}")
    print(f"       历史截断   {meta.history_cutoff}")

    if limit:
        holdout = holdout.head(limit)
    print(f"\n[回放] 待回放 {len(holdout)} 条  区间 {meta.eval_range}")
    print("       调用路径：ResponsePredictor.predict()（与生产一致）")

    probs = np.zeros(len(holdout))
    t0 = time.time()
    for i, row in enumerate(holdout.itertuples(index=False)):
        r = predictor.predict(
            PredictRequest(
                customer_id=row.customer_id,
                product_id=row.product_id,
                channel=row.channel,
                contact_date=f"{row.contact_date:%Y-%m-%d}",
            )
        )
        probs[i] = r.probability
        if (i + 1) % 1000 == 0:
            print(f"       已回放 {i + 1}/{len(holdout)} ...")
    elapsed = time.time() - t0

    y = np.asarray(holdout["responded"])
    m = evaluate(y, probs)

    print(f"\n[性能] 总耗时 {elapsed:.1f}s，平均 {elapsed / len(holdout) * 1000:.2f} ms/条")

    print("\n[指标]（模型从未见过这批数据，故为无偏估计）")
    print(f"  AUC        = {m.auc:.4f}   -> {m.auc_score:5.2f} / 17 分")
    print(
        f"  F1(最优)   = {m.f1:.4f}   -> {m.f1_score_pts:5.2f} /  7 分"
        f"   (最优阈值 {m.f1_threshold:.3f})"
    )
    print(f"  Lift@10%   = {m.lift10:.4f}   -> {m.lift_score:5.2f} /  6 分")
    print(f"  {'合计':<10} {'':8}    -> {m.total_score:5.2f} / 30 分")

    print("\n[业务视角] 决策分档的实际命中情况")
    df = pd.DataFrame({"prob": probs, "y": y})
    from .predictor import THRESHOLD_HIGH, THRESHOLD_MEDIUM

    df["bucket"] = np.where(
        df["prob"] >= THRESHOLD_HIGH,
        "HIGH",
        np.where(df["prob"] >= THRESHOLD_MEDIUM, "MEDIUM", "LOW"),
    )
    base_rate = float(df["y"].mean())
    print(f"  全体实际响应率 = {base_rate:.4f}")
    for b in ("HIGH", "MEDIUM", "LOW"):
        g = df.loc[df["bucket"] == b]
        if len(g) == 0:
            continue
        rate = float(g["y"].mean())
        print(f"  {b:<7} n={len(g):>5}  实际响应率={rate:.4f}  相对基准 {rate / base_rate:.2f}x")
    print("  -> 分档单调递减即说明决策建议对运营是有效的")

    exit_code = 0
    if check_offline:
        print("\n[一致性] 在线回放 vs 离线批量")
        customer, product = F.load_base_tables()
        holding = H.load_holding()
        events = H.load_events()
        train_raw = contacts.loc[contacts["contact_date"] < cutoff].reset_index(drop=True)

        base = pd.DataFrame(F.build_features(holdout, customer, product))
        hist = H.build_history_features(
            holdout,
            holding,
            events,
            label_col=None,
            history_source=train_raw,
            prior=meta.prior,
        )
        offline = base.merge(hist, on="contact_id", how="left")
        off_prob = predictor.pipeline.predict_proba(offline.loc[:, meta.feature_columns])[:, 1]
        # 在线结果保留 6 位小数，比较时用同一精度
        diff = float(np.abs(np.round(off_prob, 6) - probs).max())
        print(f"  最大概率差异 = {diff:.12f}")
        if diff < 1e-9:
            print("  在线与离线逐位一致，服务实现正确")
        else:
            print("  ✗ 存在差异，在线特征装配与离线不一致，需排查")
            exit_code = 1

    return exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="演示模型线上回放验证")
    ap.add_argument("--limit", type=int, default=None, help="仅回放前 N 条（快速验证）")
    ap.add_argument("--check-offline", action="store_true", help="额外比对离线批量结果是否一致")
    args = ap.parse_args(argv)
    _ = model_store  # 保持导入以便错误提示中引用 profile 常量
    return run(limit=args.limit, check_offline=args.check_offline)


if __name__ == "__main__":
    sys.exit(main())
