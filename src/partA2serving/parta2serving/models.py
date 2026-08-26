from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRanker
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier, XGBRanker

from .config import SEED
from .features import CAT_COLS, matrix_from_frame


class ResponseRanker:
    """点式分类：P(respond|c,p,ch)。"""

    def __init__(self, backend: str = "lightgbm"):
        if backend not in {"lightgbm", "xgboost"}:
            raise ValueError(backend)
        self.backend = backend
        self.model: Any = None
        self.feature_names: list[str] = []
        self.cat_levels: dict[str, list[str]] = {}
        self.mode = "binary"

    def _init_model(self) -> Any:
        if self.backend == "lightgbm":
            return LGBMClassifier(
                n_estimators=450,
                learning_rate=0.05,
                max_depth=7,
                num_leaves=63,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_lambda=1.5,
                min_child_samples=25,
                random_state=SEED,
                n_jobs=-1,
                verbose=-1,
            )
        return XGBClassifier(
            n_estimators=450,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.5,
            min_child_weight=3,
            random_state=SEED,
            n_jobs=-1,
            tree_method="hist",
            enable_categorical=True,
            eval_metric="auc",
        )

    def fit(self, frame: pd.DataFrame) -> dict[str, float]:
        X, names = matrix_from_frame(frame)
        y = frame["responded"].astype(int).to_numpy()
        self.feature_names = names
        self.cat_levels = {
            c: sorted(X[c].astype(str).unique().tolist()) for c in CAT_COLS
        }
        self.model = self._init_model()
        if self.backend == "lightgbm":
            self.model.fit(X, y, categorical_feature=CAT_COLS)
        else:
            self.model.fit(X, y)
        proba = self.model.predict_proba(X)[:, 1]
        return {
            "mode": self.mode,
            "train_auc": float(roc_auc_score(y, proba)),
            "n_rows": int(len(y)),
            "pos_rate": float(y.mean()),
        }

    def _align(self, frame: pd.DataFrame) -> pd.DataFrame:
        X, _ = matrix_from_frame(frame)
        for c in CAT_COLS:
            X[c] = pd.Categorical(X[c].astype(str), categories=self.cat_levels.get(c))
        return X[self.feature_names]

    def predict_score(self, frame: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not fitted")
        return self.model.predict_proba(self._align(frame))[:, 1]

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        return self.predict_score(frame)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "cls": type(self).__name__,
                "backend": self.backend,
                "mode": self.mode,
                "model": self.model,
                "feature_names": self.feature_names,
                "cat_levels": self.cat_levels,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "ResponseRanker":
        payload = joblib.load(path)
        obj = cls(backend=payload["backend"])
        obj.model = payload["model"]
        obj.feature_names = payload["feature_names"]
        obj.cat_levels = payload["cat_levels"]
        obj.mode = payload.get("mode", "binary")
        return obj


class ListwiseRanker:
    """LambdaMART 学习排序。"""

    def __init__(self, backend: str = "lightgbm"):
        if backend not in {"lightgbm", "xgboost"}:
            raise ValueError(backend)
        self.backend = backend
        self.model: Any = None
        self.feature_names: list[str] = []
        self.cat_levels: dict[str, list[str]] = {}
        self.mode = "ltr"

    def _init_model(self) -> Any:
        if self.backend == "lightgbm":
            return LGBMRanker(
                objective="lambdarank",
                metric="ndcg",
                n_estimators=400,
                learning_rate=0.05,
                max_depth=7,
                num_leaves=63,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_lambda=1.5,
                min_child_samples=15,
                random_state=SEED,
                n_jobs=-1,
                verbose=-1,
            )
        return XGBRanker(
            objective="rank:ndcg",
            n_estimators=400,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.5,
            min_child_weight=2,
            random_state=SEED,
            n_jobs=-1,
            tree_method="hist",
            enable_categorical=True,
        )

    def fit(self, frame: pd.DataFrame) -> dict[str, float]:
        frame = frame.sort_values(["customer_id"]).reset_index(drop=True)
        X, names = matrix_from_frame(frame)
        y = frame["relevance"].astype(int).to_numpy()
        group = frame.groupby("customer_id", sort=False).size().to_numpy()
        self.feature_names = names
        self.cat_levels = {
            c: sorted(X[c].astype(str).unique().tolist()) for c in CAT_COLS
        }
        self.model = self._init_model()
        if self.backend == "lightgbm":
            self.model.fit(X, y, group=group, categorical_feature=CAT_COLS)
        else:
            self.model.fit(X, y, group=group)
        scores = self.model.predict(X)
        pos = y >= 2
        return {
            "mode": self.mode,
            "n_rows": int(len(y)),
            "n_groups": int(len(group)),
            "pos_rate": float(pos.mean()),
            "score_gap": float(scores[pos].mean() - scores[~pos].mean())
            if pos.any() and (~pos).any()
            else 0.0,
        }

    def _align(self, frame: pd.DataFrame) -> pd.DataFrame:
        X, _ = matrix_from_frame(frame)
        for c in CAT_COLS:
            X[c] = pd.Categorical(X[c].astype(str), categories=self.cat_levels.get(c))
        return X[self.feature_names]

    def predict_score(self, frame: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not fitted")
        return np.asarray(self.model.predict(self._align(frame)), dtype=float)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "cls": type(self).__name__,
                "backend": self.backend,
                "mode": self.mode,
                "model": self.model,
                "feature_names": self.feature_names,
                "cat_levels": self.cat_levels,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "ListwiseRanker":
        payload = joblib.load(path)
        obj = cls(backend=payload["backend"])
        obj.model = payload["model"]
        obj.feature_names = payload["feature_names"]
        obj.cat_levels = payload["cat_levels"]
        obj.mode = payload.get("mode", "ltr")
        return obj


def score_products(model: Any, grid: pd.DataFrame) -> pd.DataFrame:
    """对候选行打分；多渠道时按产品取 max。

    主分用 LTR model_score（客户内 z-score）。重先验会严重伤害 HitRate@3，
    仅保留极轻的风险精确匹配加成与已持仓惩罚。
    """
    out = grid[["customer_id", "product_id", "channel"]].copy()
    out["raw"] = model.predict_score(grid)
    best = (
        out.sort_values(
            ["customer_id", "product_id", "raw"], ascending=[True, True, False]
        )
        .groupby(["customer_id", "product_id"], as_index=False)
        .first()
        .rename(columns={"channel": "best_channel", "raw": "model_score"})
    )
    cols = [
        "customer_id",
        "product_id",
        "risk_exact_match",
        "already_held",
    ]
    extra = grid.drop_duplicates(["customer_id", "product_id"])[
        [c for c in cols if c in grid.columns]
    ]
    best = best.merge(extra, on=["customer_id", "product_id"], how="left")
    best["score_z"] = best.groupby("customer_id")["model_score"].transform(
        lambda s: (s - s.mean()) / (s.std(ddof=0) + 1e-6)
    )
    best["score"] = (
        best["score_z"]
        + 0.10 * best["risk_exact_match"].fillna(0)
        - 0.05 * best["already_held"].fillna(0)
    )
    return best[["customer_id", "product_id", "score", "best_channel", "model_score"]]


def score_products_prior_only(grid: pd.DataFrame) -> pd.DataFrame:
    """纯先验排序（无模型），用于对照与融合。"""
    cols = [
        "customer_id",
        "product_id",
        "abs_risk_diff",
        "risk_exact_match",
        "risk_within_1",
        "seg_prod_rate",
        "seg_type_rate",
        "prod_resp_rate",
        "risk_prod_rate",
        "already_held",
        "can_afford",
        "type_hold_share",
        "cp_resp_rate",
    ]
    df = grid.drop_duplicates(["customer_id", "product_id"])[
        [c for c in cols if c in grid.columns]
    ].copy()
    z = lambda c: df[c].fillna(0) if c in df.columns else 0.0
    df["score"] = (
        1.00 * z("seg_prod_rate")
        + 0.70 * z("risk_prod_rate")
        + 0.40 * z("seg_type_rate")
        + 0.30 * z("prod_resp_rate")
        + 0.80 * z("risk_exact_match")
        + 0.30 * z("risk_within_1")
        + 0.25 * z("type_hold_share")
        + 0.20 * z("cp_resp_rate")
        + 0.10 * (df["can_afford"].fillna(1) if "can_afford" in df.columns else 1)
        - 0.40 * z("abs_risk_diff")
        - 0.70 * z("already_held")
    )
    df["best_channel"] = "manager"
    df["model_score"] = df["score"]
    return df[["customer_id", "product_id", "score", "best_channel", "model_score"]]


