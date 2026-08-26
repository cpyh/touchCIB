"""读取队友A1模型元数据，并转换成平台统一指标口径。"""

from __future__ import annotations

import json
import os

from . import model_store


def load_validation_metrics(model_name: str | None = None) -> dict:
    """读取demo时间留出验证指标；full模型没有独立验证集，不能用于自评。"""
    selected_model = model_name or os.getenv("A1_SERVING_MODEL", "lgbm_onehot")
    _, meta_path = model_store.model_paths("demo", selected_model)
    with open(meta_path, encoding="utf-8") as file:
        meta = json.load(file)
    metrics = dict(meta.get("metrics", {}))
    return {
        "model_version": f"a1_{selected_model}_demo_v{meta['schema_version']}",
        "feature_version": f"partA1serving_schema_v{meta['schema_version']}",
        "auc": metrics.get("auc"),
        "best_f1": metrics.get("f1"),
        "lift_at_10_percent": metrics.get("lift10"),
        "validation_rows": metrics.get("eval_n"),
        "random_state": meta.get("random_state"),
        "validation_cutoff": meta.get("train_cutoff"),
    }


__all__ = ["load_validation_metrics"]
