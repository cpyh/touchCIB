#!/usr/bin/env python3
"""预生成演示日批名单：用 LR 工件按 as-of 重算 04-09~04-14 的 8000 条名单概率。

正式提交（2026-04-15）使用提交预测文件（LGBM 版）；其余演示日期由本脚本
以 LR 基线工件现场重算，特征严格截断到对应日期之前（时间穿越约束的活演示）。
结果缓存到 src/data/outputs/roster_daily_demo.json，供 /marketing/roster
的 contact_date 参数使用。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import joblib
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.a1_features import (  # noqa: E402
    MODEL_FEATURES,
    build_contact_features,
    load_csv_sources,
)

DEMO_DATES = [
    date(2026, 1, 10),
    date(2026, 1, 14),
    date(2026, 1, 18),
    date(2026, 1, 22),
    date(2026, 1, 26),
]  # 1 月历史回放：跨过 01-21 持仓截止线，事件流实时滑动
OUTPUT = PROJECT_DIR / "src" / "data" / "outputs" / "roster_daily_demo.json"
MODEL_ARTIFACT = PROJECT_DIR / "src" / "data" / "outputs" / "a1_baseline.joblib"


def main() -> int:
    data_dir = PROJECT_DIR / "src" / "data" / "raw"
    sources = load_csv_sources(data_dir)
    artifact = joblib.load(MODEL_ARTIFACT)
    pipeline = artifact["pipeline"]
    contacts = pd.read_csv(
        data_dir / "partA_test_contacts.csv",
        dtype={"contact_id": str, "customer_id": str, "product_id": str},
    )

    result = {
        "model": artifact["model_version"],
        "feature_version": artifact["feature_version"],
        "dates": {},
    }
    for target_date in DEMO_DATES:
        print(f"[{target_date}] 构建 as-of 特征…", flush=True)
        dated = contacts.copy()
        dated["contact_date"] = target_date.isoformat()
        features = build_contact_features(
            dated,
            customers=sources["customers"],
            products=sources["products"],
            holdings=sources["holdings"],
            events=sources["events"],
            campaign_history=sources["campaigns"],
        )
        probabilities = pipeline.predict_proba(
            features[MODEL_FEATURES]
        )[:, 1]
        ordered = sorted(
            zip(contacts["contact_id"], probabilities),
            key=lambda item: (-item[1], item[0]),
        )
        result["dates"][target_date.isoformat()] = {
            str(contact_id): {
                "prob": float(probability),
                "rank": rank + 1,
            }
            for rank, (contact_id, probability) in enumerate(ordered)
        }
        print(f"[{target_date}] 完成（{len(probabilities)} 条）", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result), encoding="utf-8")
    print(f"已写出 {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
