# Part A2 Serving 交付包

A2 理财产品 Top3：**训练 + 两种推理**（客户 ID / 30×52 矩阵）。

## 目录结构

```text
partA2serving/
├── README.md                 # 本说明
├── requirements.txt          # Python 依赖
├── models/
│   └── ltr_nextbuy_lightgbm_prod.joblib
├── docs/
│   ├── a2_features_52d.md    # 52 维特征：来源表 + 计算方式
│   └── feature_columns.json  # 特征列名顺序（推理必对齐）
├── data/
│   └── README.md             # 数据放置说明（包内不含原始 CSV）
├── examples/
│   ├── quickstart.py         # 训练 + 推理示例
│   └── matrix_C000010.json   # 30×52 矩阵示例（需本地生成或随包提供）
└── parta2serving/            # Python 包
    ├── __init__.py
    ├── __main__.py             # CLI 入口
    ├── config.py / paths.py
    ├── data.py / features.py / labels.py
    ├── models.py               # ListwiseRanker
    ├── training.py             # 训练
    ├── inference.py            # 30×52 纯推理
    ├── predictor.py            # 客户 ID 推理
    └── strategy.py
```

## 快速开始

```bash
cd partA2serving
pip install -r requirements.txt

# 1) 准备数据：复制 t_*.csv 到 data/，或设置 PARTA2_DATA_DIR
set PARTA2_DATA_DIR=E:\path\to\student_pkg\student_pkg\data

# 2) 训练（可选，包内已含预训练模型）
set PYTHONPATH=%CD%
python -m parta2serving train

# 3) 推理：客户 ID
python -m parta2serving predict-top3 --customers C000010 C000012

# 4) 推理：30×52 矩阵
python -m parta2serving export-matrix-example --customer C000010
python -m parta2serving predict-matrix --input examples/matrix_C000010.json
```

## Python API

```python
from parta2serving import A2ProductRanker, predict_top3, FEATURE_COLUMNS

# 方式一：客户 ID
ranker = A2ProductRanker.load()
top3 = ranker.predict_top3(["C000010"])

# 方式二：30×52 矩阵（不读业务表）
result = predict_top3(features, product_ids)
```

## 输入契约

| 项 | 要求 |
|----|------|
| 矩阵形状 | (30, 52) |
| 列顺序 | 与 `docs/feature_columns.json` 一致 |
| product_ids | 长度 30，与每行特征对应 |

## 后处理

`LGBMRanker.predict` → 客户内 z-score → `+0.10×risk_exact_match` → `-0.05×already_held` → Top3。
