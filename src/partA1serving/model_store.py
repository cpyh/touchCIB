"""模型持久化层：训练产物的保存与加载。

为什么需要
----------
离线全量训练一次约 1.6 秒（历史特征 as-of 展开 1.31s + 拟合 0.25s），
若每次预测请求都重跑不可接受；而模型加载后单条推理仅约 9 ms。
因此必须把"训练"与"推理"彻底分离：训练一次落盘，服务启动时加载一次。

两套 profile（重要）
-------------------
本项目刻意维护两个独立模型，训练数据范围不同，用途不可混用：

  demo —— 训练数据截止 2026-01-31（42642 条）
           用于工程化演示。因为 2026-02-01 ~ 2026-03-26 的 7358 条数据
           模型从未见过且带真实标签，演示时可当场验证预测是否可信。
           默认 as-of 基准日 = 2026-01-31。

  full —— 使用全部 50000 条
           仅用于生成提交物 partA_prediction.csv。
           默认 as-of 基准日 = 2026-03-26。

若用 full 模型去演示 2026-02 之后的数据，等于用见过答案的模型自评，
指标会虚高且不可信；因此元数据中记录 `train_cutoff` 与 `eval_range`，
加载时可核对，避免误用。

产物内容
--------
除 sklearn Pipeline 本身，还必须一并保存**推理期需要的元数据**，
否则在线特征装配无法与训练期保持一致：
  - feature_columns：特征列的名称与顺序（顺序错则结果全错）
  - prior：贝叶斯平滑先验（须与训练期同值，不能在线重算）
  - as_of_date：该 profile 的默认 as-of 基准日
  - history_cutoff：历史特征可见数据的上界（严格小于此日期）
  - train_cutoff / eval_range：训练边界，用于核对是否误用
  - schema_version：产物结构版本，加载时校验，避免新旧不兼容静默出错
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import joblib

from . import config

# 产物结构版本。字段含义变更时必须递增，加载时会校验。
# v2：引入 profile 机制，新增 train_cutoff / eval_range / history_cutoff
SCHEMA_VERSION = 3


def default_models_root() -> str:
    """默认模型根目录，**运行时**解析。

    刻意不做成模块级常量：那会在 import 时固化，导致之后调用
    `bootstrap.configure(models_dir=...)` 完全不生效，
    且失败形式是静默指向旧路径，排查成本很高。
    """
    return config.MODELS_DIR


# 产物文件名按模型类型区分，使同一 profile 下可并存多种模型，便于随时回滚
def model_filename(model_name: str) -> str:
    return f"a1_response_{model_name}.joblib"


def meta_filename(model_name: str) -> str:
    return f"a1_response_{model_name}.meta.json"


# 演示模型的训练截止日（含义：训练只用 contact_date < 此日期 的数据）
DEMO_TRAIN_CUTOFF = "2026-02-01"

PROFILES = ("demo", "full")
DEFAULT_PROFILE = "demo"


@dataclass
class ModelMeta:
    """推理期必需的元数据。任何一项缺失都会导致在线与离线结果不一致。"""

    schema_version: int
    profile: str
    model_name: str
    feature_columns: list[str]
    prior: float
    as_of_date: str
    history_cutoff: str | None
    random_state: int
    use_history: bool
    n_train_rows: int
    train_range: str
    train_cutoff: str | None
    eval_range: str | None
    trained_at: str
    source_rows: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ModelMeta:
        return ModelMeta(
            schema_version=int(d["schema_version"]),
            profile=str(d["profile"]),
            model_name=str(d.get("model_name", "lr")),
            feature_columns=list(d["feature_columns"]),
            prior=float(d["prior"]),
            as_of_date=str(d["as_of_date"]),
            history_cutoff=d.get("history_cutoff"),
            random_state=int(d["random_state"]),
            use_history=bool(d["use_history"]),
            n_train_rows=int(d["n_train_rows"]),
            train_range=str(d.get("train_range", "")),
            train_cutoff=d.get("train_cutoff"),
            eval_range=d.get("eval_range"),
            trained_at=str(d["trained_at"]),
            source_rows=dict(d.get("source_rows", {})),
            metrics=dict(d.get("metrics", {})),
        )

    @property
    def is_demo(self) -> bool:
        return self.profile == "demo"


def profile_dir(profile: str, models_root: str | None = None) -> str:
    if profile not in PROFILES:
        raise ValueError(f"未知 profile={profile!r}，可选 {PROFILES}")
    return os.path.join(models_root or default_models_root(), profile)


def model_paths(
    profile: str, model_name: str = "lr", models_root: str | None = None
) -> tuple[str, str]:
    base = profile_dir(profile, models_root)
    return (
        os.path.join(base, model_filename(model_name)),
        os.path.join(base, meta_filename(model_name)),
    )


def save(pipeline: Any, meta: ModelMeta, models_root: str | None = None) -> tuple[str, str]:
    """保存模型与元数据到对应 profile 目录。"""
    base = profile_dir(meta.profile, models_root)
    os.makedirs(base, exist_ok=True)
    model_path, meta_path = model_paths(meta.profile, meta.model_name, models_root)
    joblib.dump(pipeline, model_path, compress=3)
    with open(meta_path, "w", encoding="utf-8") as fh:
        fh.write(meta.to_json())
    return model_path, meta_path


def load(
    profile: str = DEFAULT_PROFILE,
    model_name: str = "lr",
    models_root: str | None = None,
) -> tuple[Any, ModelMeta]:
    """加载指定 profile + 模型类型的产物，并校验版本与一致性。"""
    model_path, meta_path = model_paths(profile, model_name, models_root)
    if not os.path.isfile(model_path):
        raise FileNotFoundError(
            f"模型文件不存在：{model_path}\n"
            f"请先运行：python -m partA1serving.training.train_and_save "
            f"--profile {profile} --model {model_name}"
        )
    if not os.path.isfile(meta_path):
        raise FileNotFoundError(f"元数据文件不存在：{meta_path}")

    with open(meta_path, encoding="utf-8") as fh:
        meta = ModelMeta.from_dict(json.load(fh))

    if meta.schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"模型产物版本不匹配：文件为 v{meta.schema_version}，"
            f"当前代码需要 v{SCHEMA_VERSION}。请重新训练。"
        )
    if meta.model_name != model_name:
        raise ValueError(
            f"产物模型类型不一致：请求 {model_name!r}，元数据记为 {meta.model_name!r}。"
        )
    if meta.profile != profile:
        raise ValueError(
            f"产物 profile 不一致：目录为 {profile!r}，元数据记为 {meta.profile!r}。"
            f"可能是文件被手工移动，请重新训练。"
        )
    pipeline = joblib.load(model_path)
    return pipeline, meta


def build_meta(
    profile: str,
    model_name: str,
    feature_columns: list[str],
    prior: float,
    as_of_date: str,
    history_cutoff: str | None,
    use_history: bool,
    n_train_rows: int,
    train_range: str,
    train_cutoff: str | None = None,
    eval_range: str | None = None,
    source_rows: dict[str, int] | None = None,
    metrics: dict[str, Any] | None = None,
) -> ModelMeta:
    if profile not in PROFILES:
        raise ValueError(f"未知 profile={profile!r}，可选 {PROFILES}")
    return ModelMeta(
        schema_version=SCHEMA_VERSION,
        profile=profile,
        model_name=model_name,
        feature_columns=list(feature_columns),
        prior=float(prior),
        as_of_date=str(as_of_date),
        history_cutoff=history_cutoff,
        random_state=config.RANDOM_STATE,
        use_history=bool(use_history),
        n_train_rows=int(n_train_rows),
        train_range=train_range,
        train_cutoff=train_cutoff,
        eval_range=eval_range,
        trained_at=datetime.now().isoformat(timespec="seconds"),
        source_rows=dict(source_rows or {}),
        metrics=dict(metrics or {}),
    )
