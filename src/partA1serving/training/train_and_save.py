"""训练并保存模型产物，供在线服务加载。

两套 profile（用途不可混用）
---------------------------
  demo —— 训练数据仅用 contact_date < 2026-02-01（42642 条）。
           2026-02-01 ~ 2026-03-26 的 7358 条数据模型从未见过且带真实标签，
           因此工程化演示时可以当场验证预测是否可信，而不是"只给一个分数"。
           在线服务的历史特征索引同样只装载 < cutoff 的触达记录，
           从数据源头切断"看到未来标签"的可能。
           默认 as-of 基准日 = 2026-01-31。

  full —— 使用全部 50000 条。用于正式 A1/A2 提交物与平台推理；
           已见过训练期标签，不可用于现场回放自评。
           默认 as-of 基准日 = 2026-03-26。

与 predict.py 的关系
---------------------
`predict.py`、A2 正式导出和 Flask 在线服务都会加载本脚本保存的模型产物，
不再各自训练另一套模型。正式复现时先训练 full，再依次导出 A1/A2，即可保证
模型、特征列顺序、平滑先验和 as-of 历史索引完全一致。

用法
----
    python -m partA1serving.training.train_and_save                # 两套都训练
    python -m partA1serving.training.train_and_save --profile demo
    python -m partA1serving.training.train_and_save --profile full
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .. import estimators as M
from .. import features_a1 as F
from .. import features_history as H
from .. import model_store
from .pipeline import build_pipeline, evaluate, get_all_feature_columns


def _fmt_range(frame: pd.DataFrame) -> str:
    return f"{frame['contact_date'].min():%Y-%m-%d} ~ {frame['contact_date'].max():%Y-%m-%d}"


def train_demo(
    contacts: pd.DataFrame,
    customer: pd.DataFrame,
    product: pd.DataFrame,
    holding: pd.DataFrame,
    events: pd.DataFrame,
    models_root: str | None,
    model_name: str = M.DEFAULT_MODEL,
) -> None:
    """演示模型：只用 cutoff 之前的数据训练，并在 cutoff 之后的数据上评估。"""
    cutoff = pd.Timestamp(model_store.DEMO_TRAIN_CUTOFF)
    mask = np.asarray(contacts["contact_date"] < cutoff)
    train_raw = contacts.loc[mask].reset_index(drop=True)
    eval_raw = contacts.loc[~mask].reset_index(drop=True)

    prior = float(train_raw["responded"].mean())
    as_of = f"{train_raw['contact_date'].max():%Y-%m-%d}"
    feat_cols = get_all_feature_columns(True)

    print("\n" + "-" * 66)
    print(
        f"[profile=demo | model={model_name}] 训练截止 {model_store.DEMO_TRAIN_CUTOFF}（严格小于）"
    )
    print("-" * 66)
    print(f"  训练段: {len(train_raw):>6} 条  {_fmt_range(train_raw)}  正例率 {prior:.6f}")
    print(
        f"  演示段: {len(eval_raw):>6} 条  {_fmt_range(eval_raw)}  "
        f"正例率 {eval_raw['responded'].mean():.6f}"
    )
    print(f"  as-of 默认基准日 = {as_of}")

    base = pd.DataFrame(F.build_features(contacts, customer, product))
    # 训练段：历史来自训练段自身，逐行 as-of 展开
    h_train = H.build_history_features(
        train_raw, holding, events, label_col="responded", prior=prior
    )
    # 演示段：历史只能来自训练段，与线上推理口径一致
    h_eval = H.build_history_features(
        eval_raw, holding, events, label_col=None, history_source=train_raw, prior=prior
    )
    merged = base.merge(
        pd.concat([h_train, h_eval], ignore_index=True), on="contact_id", how="left"
    )
    tr = merged.loc[merged["contact_date"] < cutoff]
    va = merged.loc[merged["contact_date"] >= cutoff]

    n_na = int(tr.loc[:, feat_cols].isna().sum().sum())
    if n_na:
        raise ValueError(f"训练矩阵存在 {n_na} 个缺失值，拒绝训练")

    pipeline = build_pipeline(True, model_name)
    pipeline.fit(tr.loc[:, feat_cols], np.asarray(tr["responded"]))

    prob = pipeline.predict_proba(va.loc[:, feat_cols])[:, 1]
    m = evaluate(np.asarray(va["responded"]), prob)
    print("\n  演示段评估（模型未见过这些数据）")
    print(f"    AUC={m.auc:.4f}  F1={m.f1:.4f}  Lift@10%={m.lift10:.4f}")
    print(f"    预估得分 {m.total_score:.2f} / 30")

    meta = model_store.build_meta(
        profile="demo",
        model_name=model_name,
        feature_columns=feat_cols,
        prior=prior,
        as_of_date=as_of,
        history_cutoff=model_store.DEMO_TRAIN_CUTOFF,
        use_history=True,
        n_train_rows=len(tr),
        train_range=_fmt_range(train_raw),
        train_cutoff=model_store.DEMO_TRAIN_CUTOFF,
        eval_range=_fmt_range(eval_raw),
        source_rows={
            "t_campaign_used": len(train_raw),
            "t_campaign_total": len(contacts),
            "t_customer": len(customer),
            "t_product": len(product),
            "t_holding": len(holding),
            "t_event": len(events),
        },
        metrics={
            "auc": round(m.auc, 6),
            "f1": round(m.f1, 6),
            "lift10": round(m.lift10, 6),
            "est_score": round(m.total_score, 3),
            "eval_n": len(va),
        },
    )
    mp, tp = model_store.save(pipeline, meta, models_root)
    print(f"\n  已保存 {mp}  ({os.path.getsize(mp) / 1024:.1f} KiB)")
    print(f"        {tp}")


def train_full(
    contacts: pd.DataFrame,
    customer: pd.DataFrame,
    product: pd.DataFrame,
    holding: pd.DataFrame,
    events: pd.DataFrame,
    models_root: str | None,
    model_name: str = M.DEFAULT_MODEL,
) -> None:
    """提交模型：全量训练，与 predict.py 的口径一致。"""
    prior = float(contacts["responded"].mean())
    as_of = f"{contacts['contact_date'].max():%Y-%m-%d}"
    feat_cols = get_all_feature_columns(True)

    print("\n" + "-" * 66)
    print(f"[profile=full | model={model_name}] 全量训练（正式提交与平台推理）")
    print("-" * 66)
    print(f"  训练集: {len(contacts):>6} 条  {_fmt_range(contacts)}  正例率 {prior:.6f}")
    print(f"  as-of 默认基准日 = {as_of}")

    base = pd.DataFrame(F.build_features(contacts, customer, product))
    hist = H.build_history_features(contacts, holding, events, label_col="responded", prior=prior)
    full = base.merge(hist, on="contact_id", how="left")

    n_na = int(full.loc[:, feat_cols].isna().sum().sum())
    if n_na:
        raise ValueError(f"训练矩阵存在 {n_na} 个缺失值，拒绝训练")

    pipeline = build_pipeline(True, model_name)
    pipeline.fit(full.loc[:, feat_cols], np.asarray(full["responded"]))
    n_encoded = M.encoded_width(pipeline, full.loc[:, feat_cols].iloc[:1])
    print(f"  特征 {len(feat_cols)} 个 -> 编码后 {n_encoded} 列")
    print("  注：该 profile 已见过全部数据，不可用于自评指标")

    meta = model_store.build_meta(
        profile="full",
        model_name=model_name,
        feature_columns=feat_cols,
        prior=prior,
        as_of_date=as_of,
        history_cutoff=None,  # 不设截断，历史索引装载全量触达
        use_history=True,
        n_train_rows=len(full),
        train_range=_fmt_range(contacts),
        train_cutoff=None,
        eval_range=None,
        source_rows={
            "t_campaign_used": len(contacts),
            "t_campaign_total": len(contacts),
            "t_customer": len(customer),
            "t_product": len(product),
            "t_holding": len(holding),
            "t_event": len(events),
        },
    )
    mp, tp = model_store.save(pipeline, meta, models_root)
    print(f"\n  已保存 {mp}  ({os.path.getsize(mp) / 1024:.1f} KiB)")
    print(f"        {tp}")


def run(
    profiles: list[str],
    models_root: str | None = None,
    model_name: str = M.DEFAULT_MODEL,
) -> None:
    customer, product = F.load_base_tables()
    contacts = F.load_train_contacts()
    holding = H.load_holding()
    events = H.load_events()

    print("=" * 66)
    print("训练并保存 A1 营销响应预测模型")
    print("=" * 66)
    print(
        f"\n[数据] 触达 {len(contacts)}，客户 {len(customer)}，产品 {len(product)}，"
        f"持仓 {len(holding)}，事件 {len(events)}"
    )

    if "demo" in profiles:
        train_demo(contacts, customer, product, holding, events, models_root, model_name)
    if "full" in profiles:
        train_full(contacts, customer, product, holding, events, models_root, model_name)

    print("\n" + "=" * 66)
    print("验证服务可用：")
    print(f"  python -m partA1serving.cli --profile demo --model {model_name} \\")
    print("      --customer-id C000001 --product-id P002 --channel manager")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="训练并保存 A1 模型")
    ap.add_argument(
        "--profile",
        choices=[*model_store.PROFILES, "all"],
        default="all",
        help="要训练的 profile，默认两套都训练",
    )
    ap.add_argument(
        "--model",
        default=M.DEFAULT_MODEL,
        choices=M.list_models(),
        help="模型类型，默认 lr",
    )
    ap.add_argument("--models-root", default=None, help="模型根目录，默认包内 artifacts/")
    args = ap.parse_args(argv)

    profiles = list(model_store.PROFILES) if args.profile == "all" else [args.profile]
    run(profiles, args.models_root, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
