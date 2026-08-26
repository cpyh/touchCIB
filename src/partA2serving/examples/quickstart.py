"""Part A2 Serving 快速示例：加载模型 → 客户 ID 推理 → 矩阵推理。"""
from __future__ import annotations

import json
from pathlib import Path

from parta2serving import A2ProductRanker, FEATURE_COLUMNS, predict_top3_simple

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "examples" / "matrix_C000010.json"


def main() -> None:
    print("feature columns:", len(FEATURE_COLUMNS))

    ranker = A2ProductRanker.load()
    df = ranker.predict_top3(["C000010"], include_scores=True)
    print("\n[predict by customer_id]\n", df.to_string(index=False))

    if MATRIX.exists():
        payload = json.loads(MATRIX.read_text(encoding="utf-8"))
        pairs = predict_top3_simple(payload["features"], payload["product_ids"])
        print("\n[predict by 30x52 matrix]\n", pairs)


if __name__ == "__main__":
    main()
