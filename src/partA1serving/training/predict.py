"""用已落盘的 full A1 模型生成 `partA_prediction.csv`。

正式导出与 Flask/A2 共用 ``ResponsePredictor``，避免出现“提交脚本重新训练一套、
平台加载另一套模型”的口径漂移。运行前先执行 ``train_and_save --profile full``；
模型、特征装配、as-of 历史索引和线上服务因此只有一套实现。

输出精度
--------
概率保留 6 位小数。题面说明后台按 **3 位小数去重**扫描 F1 阈值，
若输出精度过低（如 2 位小数）会让候选阈值锐减到约 101 个，
搜索变粗、F1 吃亏。校验器会对此给出提醒。

用法
----
    python -m partA1serving.training.predict
    python -m partA1serving.training.predict --model lgbm_onehot
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from .. import config
from .. import estimators as M
from ..data_source import CsvDataSource
from ..feature_service import PredictRequest
from ..predictor import ResponsePredictor


def generate(
    verbose: bool = True,
    model: str = "lgbm_onehot",
    *,
    predictor: ResponsePredictor | None = None,
    test_contacts: pd.DataFrame | None = None,
    batch_size: int = 1_000,
) -> pd.DataFrame:
    """加载 full 模型产物，对官方测试触达记录批量推理。"""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    test_raw = (
        test_contacts.copy()
        if test_contacts is not None
        else pd.read_csv(config.TEST_CONTACTS_CSV, parse_dates=["contact_date"])
    )
    required = {"contact_id", "customer_id", "product_id", "channel", "contact_date"}
    missing = sorted(required - set(test_raw.columns))
    if missing:
        raise ValueError(f"测试触达缺少字段：{missing}")
    if test_raw["contact_id"].duplicated().any():
        raise ValueError("测试触达存在重复 contact_id")
    predictor = predictor or ResponsePredictor(
        profile="full",
        model=model,
        data_source=CsvDataSource(),
    )

    if verbose:
        print("=" * 66)
        print(f"生成 A1 提交文件 partA_prediction.csv | 模型=full/{model}")
        print(f"  复用已落盘模型与线上特征服务：{M.describe(model)}")
        print("=" * 66)
        print(f"\n[数据] 测试触达 {len(test_raw)} 条")

    probabilities: list[float] = []
    for start in range(0, len(test_raw), batch_size):
        chunk = test_raw.iloc[start : start + batch_size]
        requests = [
            PredictRequest(
                customer_id=str(row.customer_id),
                product_id=str(row.product_id),
                channel=str(row.channel),
                contact_date=f"{pd.Timestamp(row.contact_date):%Y-%m-%d}",
            )
            for row in chunk.itertuples(index=False)
        ]
        results = predictor.predict_batch(requests, explain=False)
        probabilities.extend(float(result.probability) for result in results)

    out = pd.DataFrame(
        {
            "contact_id": test_raw["contact_id"].astype(str).to_numpy(),
            "response_prob": probabilities,
        }
    )

    if verbose:
        prob = out["response_prob"]
        prior = float(getattr(predictor.meta, "prior", 0.0))
        print("\n[预测分布]")
        print(f"  均值   : {prob.mean():.6f}（训练集正例率 {prior:.6f}）")
        print(f"  区间   : [{prob.min():.6f}, {prob.max():.6f}]")
        qs = prob.quantile([0.10, 0.25, 0.50, 0.75, 0.90]).to_numpy()
        print("  分位数 : p10={:.4f} p25={:.4f} p50={:.4f} p75={:.4f} p90={:.4f}".format(*qs))
        n_distinct3 = prob.round(3).nunique()
        print(f"  按 3 位小数去重的不同值: {n_distinct3}（后台据此扫描 F1 阈值，越多越好）")

    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 partA_prediction.csv")
    ap.add_argument(
        "--out",
        default=os.path.join(config.SUBMISSION_DIR, config.FILE_PREDICTION),
        help="输出路径，默认 submission/partA_prediction.csv",
    )
    ap.add_argument(
        "--model",
        default="lgbm_onehot",
        choices=M.list_models(),
        help="模型类型，默认正式模型 lgbm_onehot",
    )
    args = ap.parse_args(argv)

    out = generate(model=args.model)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out.to_csv(args.out, index=False)
    size_mib = os.path.getsize(args.out) / config.MIB
    print(f"\n已写出 {args.out}")
    print(f"  行数 {len(out)}  大小 {size_mib:.3f} MiB（上限 5 MiB）")
    print("\n请运行校验器确认格式：")
    print("  python -m src.scripts.check_submission")
    return 0


if __name__ == "__main__":
    sys.exit(main())
