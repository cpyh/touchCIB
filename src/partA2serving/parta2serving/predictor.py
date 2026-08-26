"""A2 产品 Top3 推理封装：输入客户列表 → 输出 rank + product_id。"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from .config import STRATEGY_ASOF
from .data import load_tables
from .features import build_product_grid
from .models import ListwiseRanker, score_products
from .strategy import top3_from_scores
from .training import (
    DEFAULT_LTR_MODEL_PATH,
    ctx_from_asof,
    train_ltr_model,
)


class A2ProductRanker:
    """
    加载已训 LGBMRanker，对任意客户列表推理 Top3 产品。

    示例::

        ranker = A2ProductRanker.load()
        top3 = ranker.predict_top3(["C000010", "C000012"])
        # columns: customer_id, rank, product_id
    """

    def __init__(
        self,
        model: ListwiseRanker,
        ctx: dict,
        *,
        as_of: str | pd.Timestamp = STRATEGY_ASOF,
        model_path: Path | str | None = None,
    ) -> None:
        self.model = model
        self.ctx = ctx
        self.as_of = pd.Timestamp(as_of)
        self.model_path = Path(model_path) if model_path else DEFAULT_LTR_MODEL_PATH

    @classmethod
    def train(
        cls,
        *,
        model_path: str | Path | None = None,
        train_windows: list[tuple[str, str]] | None = None,
        as_of: str | pd.Timestamp = STRATEGY_ASOF,
        tables: dict | None = None,
    ) -> tuple["A2ProductRanker", dict]:
        """训练并保存模型，返回可推理实例。"""
        path = Path(model_path) if model_path else DEFAULT_LTR_MODEL_PATH
        tables = tables or load_tables()
        model, meta = train_ltr_model(
            model_path=path,
            train_windows=train_windows,
            tables=tables,
        )
        ctx, _ = ctx_from_asof(tables, as_of)
        return cls(model, ctx, as_of=as_of, model_path=path), meta

    @classmethod
    def load(
        cls,
        model_path: str | Path | None = None,
        *,
        as_of: str | pd.Timestamp = STRATEGY_ASOF,
        tables: dict | None = None,
    ) -> "A2ProductRanker":
        path = Path(model_path) if model_path else DEFAULT_LTR_MODEL_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"模型文件不存在: {path}。请先运行: python -m src.a2 train"
            )
        tables = tables or load_tables()
        ctx, _ = ctx_from_asof(tables, as_of)
        model = ListwiseRanker.load(path)
        return cls(model, ctx, as_of=as_of, model_path=path)

    @classmethod
    def load_or_train(
        cls,
        *,
        model_path: str | Path | None = None,
        retrain: bool = False,
        as_of: str | pd.Timestamp = STRATEGY_ASOF,
        train_windows: list[tuple[str, str]] | None = None,
        tables: dict | None = None,
    ) -> tuple["A2ProductRanker", dict | None]:
        """模型文件存在则加载；否则训练。retrain=True 时强制重训。"""
        path = Path(model_path) if model_path else DEFAULT_LTR_MODEL_PATH
        if retrain or not path.exists():
            ranker, meta = cls.train(
                model_path=path,
                train_windows=train_windows,
                as_of=as_of,
                tables=tables,
            )
            return ranker, meta
        return cls.load(path, as_of=as_of, tables=tables), None

    def predict_top3(
        self,
        customer_ids: Sequence[str],
        *,
        include_scores: bool = False,
    ) -> pd.DataFrame:
        """
        对客户列表推理 Top3 理财产品。

        Parameters
        ----------
        customer_ids
            客户 ID 列表，如 ``["C000010", "C000012"]``。
        include_scores
            为 True 时额外返回 ``model_score``、``score``（含 z-score 与轻规则）。

        Returns
        -------
        DataFrame
            默认列 ``customer_id, rank, product_id``；每位客户 3 行，rank ∈ {1,2,3}。
        """
        if not customer_ids:
            return pd.DataFrame(columns=["customer_id", "rank", "product_id"])

        ids = [str(c) for c in customer_ids]
        grid = build_product_grid(ids, self.ctx, channel="manager")
        scores = score_products(self.model, grid)
        top3 = top3_from_scores(scores)
        cols = ["customer_id", "rank", "product_id"]
        if include_scores:
            cols = ["customer_id", "rank", "product_id", "model_score", "score"]
            return top3[cols].copy().reset_index(drop=True)
        return top3[cols].copy().reset_index(drop=True)

    def predict_one(self, customer_id: str, **kwargs) -> pd.DataFrame:
        """单客户 Top3，返回 3 行。"""
        return self.predict_top3([customer_id], **kwargs)


def predict_top3_products(
    customer_ids: Sequence[str],
    *,
    model_path: str | Path | None = None,
    retrain: bool = False,
    as_of: str | pd.Timestamp = STRATEGY_ASOF,
    include_scores: bool = False,
) -> pd.DataFrame:
    """便捷函数：加载/训练模型并对客户列表推理 Top3。"""
    ranker, _ = A2ProductRanker.load_or_train(
        model_path=model_path,
        retrain=retrain,
        as_of=as_of,
    )
    return ranker.predict_top3(customer_ids, include_scores=include_scores)
