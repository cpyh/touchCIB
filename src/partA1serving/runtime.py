"""Flask 平台使用的 A1 预测器单例。"""

from __future__ import annotations

import os
from functools import lru_cache

from .data_source import MySQLDataSource
from .predictor import ResponsePredictor


@lru_cache(maxsize=1)
def get_mysql_predictor() -> ResponsePredictor:
    """延迟加载模型和 DWD 历史索引，避免 import Flask 应用时连接数据库。"""
    return ResponsePredictor(
        profile=os.getenv("A1_SERVING_PROFILE", "full"),
        model=os.getenv("A1_SERVING_MODEL", "lgbm_onehot"),
        data_source=MySQLDataSource(),
    )


def clear_mysql_predictor() -> None:
    """数据批次重建后主动清缓存；主要供测试和演示运维使用。"""
    get_mysql_predictor.cache_clear()


__all__ = ["clear_mysql_predictor", "get_mysql_predictor"]
