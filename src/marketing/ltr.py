"""A2 LTR 学习排序模型适配器：产品排序主信号 + ADS 落库。

队友 partA2serving 包（LGBMRanker · 52 维特征 · 学习"下一周期实际购买"标签）
取代此前的"持有产品协同过滤"作为产品排序主信号：

- ltr_score_map: (customer_id, product_id) -> LTR 策略分（30 产品全覆盖）；
- 模型/依赖不可用时返回空映射，引擎自动回退到 A1 概率排序，不阻断平台；
- persist_ltr_top3: 把 2000 位目标客户的 Top3 评分 upsert 进
  ads_a2_strategy_score（ADS 层算法产物）。
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import pandas as pd

from ..database import database_connection

PROJECT_DIR = Path(__file__).resolve().parents[2]
PARTA2_PKG = PROJECT_DIR / "src" / "partA2serving"
RAW_DIR = PROJECT_DIR / "src" / "data" / "raw"
STRATEGY_ASOF = "2026-04-15"
LTR_MODEL_VERSION = "ltr_nextbuy_lightgbm_prod"

logger = logging.getLogger(__name__)


def _ensure_importable() -> None:
    if str(PARTA2_PKG) not in sys.path:
        sys.path.insert(0, str(PARTA2_PKG))


@lru_cache(maxsize=1)
def _context() -> dict:
    _ensure_importable()
    from parta2serving.data import load_tables
    from parta2serving.training import ctx_from_asof

    tables = load_tables(data_dir=RAW_DIR)
    ctx, _ = ctx_from_asof(tables, STRATEGY_ASOF)
    return ctx


@lru_cache(maxsize=1)
def _ranker():
    _ensure_importable()
    from parta2serving.models import ListwiseRanker
    from parta2serving.training import DEFAULT_LTR_MODEL_PATH

    return ListwiseRanker.load(DEFAULT_LTR_MODEL_PATH)


def ltr_available() -> bool:
    """LTR 模型是否可用（依赖缺失/文件缺失时优雅降级）。"""
    try:
        _ranker()
        return True
    except Exception as exc:  # noqa: BLE001 - 降级路径，记录原因即可
        logger.warning("A2 LTR 模型不可用，回退 A1 概率排序：%s", exc)
        return False


def ltr_full_scores(customer_ids: Sequence[str]) -> pd.DataFrame:
    """30 产品全覆盖的 LTR 评分。

    columns: customer_id, product_id, model_score, score
    """
    if not customer_ids or not ltr_available():
        return pd.DataFrame(
            columns=["customer_id", "product_id", "model_score", "score"]
        )
    _ensure_importable()
    from parta2serving.features import build_product_grid
    from parta2serving.models import score_products

    grid = build_product_grid(list(dict.fromkeys(customer_ids)), _context())
    return score_products(_ranker(), grid)


def ltr_score_map(customer_ids: Sequence[str]) -> dict[tuple[str, str], float]:
    """(customer_id, product_id) -> LTR 策略分（引擎产品排序主信号）。"""
    scores = ltr_full_scores(customer_ids)
    return {
        (row.customer_id, row.product_id): float(row.score)
        for row in scores.itertuples()
    }


def ltr_top3(customer_ids: Sequence[str]) -> pd.DataFrame:
    """Top3 结果：customer_id, rank, product_id, model_score, score。"""
    scores = ltr_full_scores(customer_ids)
    if scores.empty:
        return pd.DataFrame(
            columns=["customer_id", "rank", "product_id", "model_score", "score"]
        )
    _ensure_importable()
    from parta2serving.strategy import top3_from_scores

    return top3_from_scores(scores)


def persist_ltr_top3(customer_ids: Sequence[str], as_of_date: str) -> int:
    """把 Top3 评分 upsert 进 ads_a2_strategy_score，返回写入行数。"""
    frame = ltr_top3(customer_ids)
    if frame.empty:
        return 0
    rows = [
        (
            row.customer_id,
            int(row.rank),
            row.product_id,
            float(row.model_score) if pd.notna(row.model_score) else None,
            float(row.score) if pd.notna(row.score) else None,
            LTR_MODEL_VERSION,
            as_of_date,
        )
        for row in frame.itertuples()
    ]
    statement = (
        "INSERT INTO ads_a2_strategy_score "
        "(customer_id, strategy_rank, product_id, model_score, combined_score, "
        "model_version, as_of_date) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) AS new ON DUPLICATE KEY UPDATE "
        "product_id = new.product_id, model_score = new.model_score, "
        "combined_score = new.combined_score, model_version = new.model_version, "
        "as_of_date = new.as_of_date, generated_at = CURRENT_TIMESTAMP"
    )
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.executemany(statement, rows)
        connection.commit()
    finally:
        connection.close()
    return len(rows)
