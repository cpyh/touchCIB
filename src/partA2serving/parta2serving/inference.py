"""A2 纯推理：30×52 特征矩阵 → Top3 产品（不读业务表）。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .config import MODEL_DIR
from .features import CAT_COLS, FEATURE_COLUMNS, NUM_COLS
from .models import ListwiseRanker

N_PRODUCTS = 30
N_FEATURES = len(FEATURE_COLUMNS)

DEFAULT_MODEL_PATH = MODEL_DIR / "ltr_nextbuy_lightgbm_prod.joblib"

# 轻规则修正所用列（均在 52 维特征内）
_RULE_RISK_EXACT = "risk_exact_match"
_RULE_ALREADY_HELD = "already_held"
_RULE_RISK_BONUS = 0.10
_RULE_HELD_PENALTY = 0.05


@lru_cache(maxsize=4)
def _load_ranker(model_path: str) -> ListwiseRanker:
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 LTR 模型: {path}。"
            "请先运行: python -m src.a2 predict --backend ltr_a1"
        )
    return ListwiseRanker.load(path)


def features_to_frame(
    features: Sequence[Sequence[Any]] | np.ndarray,
    product_ids: Sequence[str],
) -> pd.DataFrame:
    """将 30×52 列表转为带列名的 DataFrame。"""
    arr = np.asarray(features, dtype=object)
    if arr.shape != (N_PRODUCTS, N_FEATURES):
        raise ValueError(
            f"features 形状应为 ({N_PRODUCTS}, {N_FEATURES})，实际为 {arr.shape}"
        )
    if len(product_ids) != N_PRODUCTS:
        raise ValueError(
            f"product_ids 长度应为 {N_PRODUCTS}，实际为 {len(product_ids)}"
        )
    df = pd.DataFrame(arr, columns=FEATURE_COLUMNS)
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    for c in CAT_COLS:
        df[c] = df[c].astype(str)
    df["product_id"] = [str(p) for p in product_ids]
    return df


def score_from_frame(frame: pd.DataFrame, model: ListwiseRanker) -> pd.DataFrame:
    """LGBMRanker 打分 + 客户内 z-score + 轻规则（单客户 30 产品）。"""
    out = frame[["product_id"]].copy()
    out["model_score"] = model.predict_score(frame)
    z = out["model_score"].astype(float)
    out["score_z"] = (z - z.mean()) / (z.std(ddof=0) + 1e-6)
    risk_exact = frame[_RULE_RISK_EXACT].fillna(0).astype(float)
    already_held = frame[_RULE_ALREADY_HELD].fillna(0).astype(float)
    out["score"] = (
        out["score_z"]
        + _RULE_RISK_BONUS * risk_exact
        - _RULE_HELD_PENALTY * already_held
    )
    return out


def predict_top3(
    features: Sequence[Sequence[Any]] | np.ndarray,
    product_ids: Sequence[str],
    *,
    model: ListwiseRanker | None = None,
    model_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    单客户 Top3 产品推理。

    Parameters
    ----------
    features : 30×52 特征矩阵，列顺序同 FEATURE_COLUMNS（NUM_COLS + CAT_COLS）
    product_ids : 长度 30，与 features 每行一一对应的产品 ID

    Returns
    -------
    [{"rank": 1, "product_id": "P007", "score": ..., "model_score": ...}, ...] 共 3 条
    """
    frame = features_to_frame(features, product_ids)
    ranker = model or _load_ranker(str(model_path or DEFAULT_MODEL_PATH))
    scored = score_from_frame(frame, ranker)
    top3 = (
        scored.sort_values("score", ascending=False)
        .head(3)
        .reset_index(drop=True)
    )
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(top3.itertuples(index=False), start=1):
        rows.append(
            {
                "rank": i,
                "product_id": str(r.product_id),
                "score": float(r.score),
                "model_score": float(r.model_score),
            }
        )
    return rows


def predict_top3_simple(
    features: Sequence[Sequence[Any]] | np.ndarray,
    product_ids: Sequence[str],
    *,
    model: ListwiseRanker | None = None,
    model_path: Path | str | None = None,
) -> list[tuple[int, str]]:
    """仅返回 [(rank, product_id), ...] 共 3 项。"""
    return [
        (item["rank"], item["product_id"])
        for item in predict_top3(
            features, product_ids, model=model, model_path=model_path
        )
    ]
