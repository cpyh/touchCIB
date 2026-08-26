"""LogisticRegression 基线模型。

本模块从 `train_a1_baseline.build_pipeline()` 原样迁移而来，**行为完全一致**：
同样的编码方式、同样的超参、同样的随机种子。迁移的唯一目的是让模型定义
可被注册表统一管理，从而支持 `--model` 切换。

`tests/test_models.py` 中有断言校验本实现与迁移前逐位一致，
确保引入多模型机制没有意外改变基线行为。

编码方式
--------
- 13 个类别特征 -> one-hot（`handle_unknown='ignore'`，测试集出现未见类别不报错）
- `aum` / `min_invest` 高度右偏（aum 最大值是中位数的 58 倍）-> log1p 后标准化
- 其余数值特征 -> 标准化
合计展开为 138 列。
"""

from __future__ import annotations

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from .. import config
from .. import features_a1 as F
from .. import features_history as H


def numeric_columns(use_history: bool) -> list[str]:
    cols = list(F.NUMERIC_ALL)
    if use_history:
        cols += H.get_history_columns()
    return cols


def build(use_history: bool = True, **params) -> Pipeline:
    """类别 one-hot + 数值（偏态列 log1p 后）标准化 + LogisticRegression。

    Args:
        use_history: 是否纳入 16 个历史统计特征。
        **params: 透传给 LogisticRegression 的超参（基线不调参，保持默认）。
    """
    numeric_all = numeric_columns(use_history)
    log_cols = [c for c in F.LOG_SCALE_COLS if c in numeric_all]
    plain_cols = [c for c in numeric_all if c not in log_cols]

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

    clf_params: dict = {"max_iter": 2000, "random_state": config.RANDOM_STATE}
    clf_params.update(params)
    return Pipeline([("pre", pre), ("clf", LogisticRegression(**clf_params))])
