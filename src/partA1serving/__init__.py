"""partA1serving —— Part A1 营销响应预测服务包（自包含）。

本包把 A1 的全部能力收敛到一个目录：特征工程、模型定义、训练/预测/调参、
模型产物、在线推理服务。对外提供两类接口：

在线推理（作为库）
------------------
    from partA1serving import ResponsePredictor, PredictRequest

    predictor = ResponsePredictor(profile="full", model="lgbm_onehot")
    r = predictor.predict(PredictRequest(customer_id="C000001",
                                         product_id="P002",
                                         channel="manager"))

部署引导
--------
    from partA1serving import bootstrap

    bootstrap.configure(data_dir="/srv/wmp/data")   # 数据路径用环境变量/显式覆盖
    report = bootstrap.verify(profile="full", model="lgbm_onehot")

离线批处理（命令行）
--------------------
    python -m partA1serving.training.train_and_save --profile full --model lgbm_onehot
    python -m partA1serving.training.predict --model lgbm_onehot
    python -m partA1serving.cli --customer-id C000001 --product-id P002 --channel manager

目录结构
--------
    config.py        自包含配置（路径解析 + 常量，不依赖 ../spec.py）
    bootstrap.py     部署引导（路径覆盖 + 启动自检）
    features_a1.py / features_history.py   特征工程
    estimators/      模型定义（lr / lgbm / lgbm_onehot）
    training/        训练 / 预测 / 调参（离线批处理）
    artifacts/       训练产物（demo/ full/ tuning_*.json），随包内置
    predictor.py / feature_service.py / history_index.py / model_store.py
                    在线推理服务

注意：数据目录（data/）不随包内置，启动时通过 WMP_DATA_DIR 环境变量或
bootstrap.configure(data_dir=...) 注入。
"""

from __future__ import annotations

from . import bootstrap
from . import model_store
from .data_source import A1DataBundle, A1DataSource, CsvDataSource, MySQLDataSource
from .feature_service import (
    FeatureAssemblyError,
    FeatureService,
    PredictRequest,
)
from .predictor import PredictResult, ResponsePredictor

__all__ = [
    "FeatureAssemblyError",
    "FeatureService",
    "A1DataBundle",
    "A1DataSource",
    "CsvDataSource",
    "MySQLDataSource",
    "PredictRequest",
    "PredictResult",
    "ResponsePredictor",
    "bootstrap",
    "model_store",
]
