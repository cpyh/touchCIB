"""LightGBM 模型（两种类别编码变体）。

为什么提供两种变体
------------------
- `lgbm`（原生 category）：树模型处理类别特征的推荐做法。
  LightGBM 对 category 列使用专门的分裂算法（按类别的目标均值排序后寻找最优切分），
  无需 one-hot 展开，通常比稀疏高维输入更强。
- `lgbm_onehot`（one-hot）：与 LR 编码完全同源。
  它的意义在于隔离变量——把 `lgbm_onehot` 与 `lr` 对比，差异只来自模型本身；
  把 `lgbm` 与 `lgbm_onehot` 对比，差异只来自编码方式。

复现性（重要）
--------------
LightGBM 多线程时直方图构建的浮点累加顺序不确定，会导致同一份数据多次训练
得到微小不同的结果。题面要求"重跑结果应与提交 CSV 高度吻合"，且 LR 已做到
逐位一致，因此这里**强制单线程**（`n_jobs=1`）并固定全部随机源，
使 LightGBM 同样可逐位复现。数据规模仅 5 万行 × 46 特征，单线程开销可接受。

`deterministic=True` 与 `force_row_wise=True` 一并开启：
前者要求 LightGBM 使用确定性算法，后者固定直方图构建方式，
避免其根据数据规模自动选择 row/col-wise 而引入不确定性。
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from .. import config
from .. import features_a1 as F
from .. import features_history as H

# 保守的默认超参。LightGBM 在 5 万行小样本上极易过拟合，
# 因此默认值偏向强正则；具体取值由 tune.py 在训练段内部用时序 CV 选出。
DEFAULT_PARAMS: dict = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": -1,
    "min_child_samples": 50,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
}

# 复现性相关参数，不参与调参，始终固定
_DETERMINISM: dict = {
    "n_jobs": 1,  # 强制单线程：多线程会因浮点累加顺序不定而破坏逐位复现
    "deterministic": True,
    "force_row_wise": True,
    "random_state": config.RANDOM_STATE,
    "verbose": -1,
}


def numeric_columns(use_history: bool) -> list[str]:
    cols = list(F.NUMERIC_ALL)
    if use_history:
        cols += H.get_history_columns()
    return cols


class CategoryCaster(BaseEstimator, TransformerMixin):
    """把指定列转为 pandas `category` dtype，并在 fit 时固定类别集合。

    为什么需要固定类别集合：
    若 transform 时按各批数据自行推断类别，train 与 test 的类别编码会错位
    （同一个整数码对应不同类别），导致预测结果错误且不报错。
    因此在 fit 阶段记录每列的类别全集，transform 时统一套用；
    推理期出现的未见类别会成为 NaN，LightGBM 将其作为缺失值处理。
    """

    def __init__(self, columns: list[str]) -> None:
        self.columns = columns

    def fit(self, X: pd.DataFrame, y=None) -> CategoryCaster:
        self.categories_: dict[str, pd.Index] = {}
        for col in self.columns:
            # 排序保证类别顺序稳定，避免因数据顺序不同而改变编码
            self.categories_[col] = pd.Index(sorted(pd.Series(X[col]).dropna().unique()))
        self.feature_names_in_ = list(X.columns)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(X).copy()
        for col in self.columns:
            cats = self.categories_[col]
            out[col] = pd.Categorical(out[col], categories=cats)
        return out

    def get_feature_names_out(self, input_features=None):
        return np.asarray(self.feature_names_in_, dtype=object)


def load_tuned_params(model_name: str) -> dict:
    """读取 tune.py 产出的最优超参；文件不存在时返回空字典（用默认值）。

    这样"调参"与"训练"解耦：调参结果落盘为 JSON，训练时自动加载，
    既避免把超参硬编码进代码，也让调参可追溯（JSON 内含 CV-AUC 与 Top5）。
    """
    path = os.path.join(config.MODELS_DIR, f"tuning_{model_name}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return dict(json.load(fh).get("best_params", {}))
    except (OSError, ValueError):
        return {}


def _make_classifier(**params):
    """延迟导入 lightgbm：未安装时其余模型仍可正常使用。"""
    try:
        from lightgbm import LGBMClassifier
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "使用 LightGBM 需先安装依赖：\n"
            "  uv pip install lightgbm\n"
            "macOS 还需要 OpenMP 运行库：brew install libomp"
        ) from exc

    merged = dict(DEFAULT_PARAMS)
    merged.update(params)
    merged.update(_DETERMINISM)  # 复现性参数不可被覆盖
    return LGBMClassifier(**merged)


def build_native(use_history: bool = True, **params) -> Pipeline:
    """变体一：类别特征使用原生 category（46 列）。

    数值特征不做标准化——树模型只依赖大小顺序，缩放不影响分裂点选择，
    省去变换可减少一处潜在的训练/推理不一致来源。
    """
    cat_cols = list(F.CATEGORICAL_ALL)
    num_cols = numeric_columns(use_history)
    all_cols = cat_cols + num_cols
    # 调参结果优先于默认值，显式传入的参数优先于调参结果
    params = {**load_tuned_params("lgbm"), **params}

    return Pipeline(
        [
            ("select", FunctionTransformer(lambda X: pd.DataFrame(X).loc[:, all_cols])),
            ("cast", CategoryCaster(cat_cols)),
            ("clf", _make_classifier(**params)),
        ]
    )


def build_onehot(use_history: bool = True, **params) -> Pipeline:
    """变体二：类别特征使用 one-hot（138 列），编码与 LR 完全同源。

    保留 log1p + 标准化，使输入矩阵与 LR 逐列一致，
    这样与 `lr` 对比时唯一变量就是模型本身。
    """
    numeric_all = numeric_columns(use_history)
    log_cols = [c for c in F.LOG_SCALE_COLS if c in numeric_all]
    plain_cols = [c for c in numeric_all if c not in log_cols]
    params = {**load_tuned_params("lgbm_onehot"), **params}

    log_pipe = Pipeline(
        [
            ("log1p", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
            ("scale", StandardScaler()),
        ]
    )
    pre = ColumnTransformer(
        [
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                F.CATEGORICAL_ALL,
            ),
            ("num_log", log_pipe, log_cols),
            ("num", StandardScaler(), plain_cols),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    return Pipeline([("pre", pre), ("clf", _make_classifier(**params))])
