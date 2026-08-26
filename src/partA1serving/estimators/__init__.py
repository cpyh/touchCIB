"""模型注册表：把"模型定义"与"训练/评估/预测流程"解耦。

设计目的
--------
1. **可插拔**：新增模型只需在本包内加一个模块并注册，
   训练、评估、预测、在线服务四条链路都无需改动。
2. **可回滚**：默认模型固定为 `lr`（LogisticRegression 基线）。
   删除任一模型模块或去掉 `--model` 参数即可回到原有行为，
   LR 的代码路径不受任何影响。
3. **口径一致**：所有模型共用同一套 46 个特征与同一份
   `feature_columns` 顺序，保证对比公平、在线离线一致。

使用
----
    from partA1serving.estimators import build_model, list_models, DEFAULT_MODEL

    pipe = build_model("lr")                      # 与改造前完全等价
    pipe = build_model("lgbm")                    # 原生 category 编码
    pipe = build_model("lgbm_onehot")             # one-hot 编码，与 LR 同源

约定
----
每个模型模块须提供 `build(use_history: bool, **params) -> Pipeline`，
返回的 Pipeline 必须：
  - 接受原始特征 DataFrame（列名与 get_feature_columns() 一致）；
  - 自行完成编码与缩放（因此可以自由选择 one-hot 或原生 category）；
  - 暴露 `predict_proba`。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import lgbm as _lgbm
from . import lr as _lr

# name -> 构建函数
_REGISTRY: dict[str, Callable[..., Any]] = {
    "lr": _lr.build,
    "lgbm": _lgbm.build_native,
    "lgbm_onehot": _lgbm.build_onehot,
}

# 默认模型。保持为 lr，确保未显式指定时行为与改造前完全一致。
DEFAULT_MODEL = "lr"

# 模型说明，供 CLI --help 与文档使用
DESCRIPTIONS: dict[str, str] = {
    "lr": "LogisticRegression 基线（one-hot + 标准化，138 列）",
    "lgbm": "LightGBM，类别特征用原生 category（46 列，树模型推荐做法）",
    "lgbm_onehot": "LightGBM，类别特征用 one-hot（138 列，与 lr 同源便于对比）",
}


def list_models() -> list[str]:
    return list(_REGISTRY)


def build_model(name: str = DEFAULT_MODEL, use_history: bool = True, **params: Any) -> Any:
    """按名称构建模型 Pipeline。"""
    if name not in _REGISTRY:
        raise ValueError(
            f"未知模型 {name!r}。可选：{list_models()}\n"
            + "\n".join(f"  {k}: {v}" for k, v in DESCRIPTIONS.items())
        )
    return _REGISTRY[name](use_history=use_history, **params)


def describe(name: str) -> str:
    return DESCRIPTIONS.get(name, name)


__all__ = ["DEFAULT_MODEL", "DESCRIPTIONS", "build_model", "describe", "list_models"]


def encoded_width(pipeline: Any, sample: Any) -> int:
    """返回模型实际输入的列数。

    不同模型的预处理步骤名不同（lr/lgbm_onehot 有 "pre"，lgbm 用 "cast"），
    因此统一按"除最后一步分类器外的所有步骤"来变换，避免调用方硬编码步骤名。
    """
    x = sample
    for _, step in pipeline.steps[:-1]:
        x = step.transform(x)
    return int(getattr(x, "shape", (0, 0))[1])
