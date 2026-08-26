"""Part A2 serving: LTR 训练 + Top3 推理。"""

from .config import DEFAULT_MODEL_PATH
from .features import FEATURE_COLUMNS
from .inference import N_FEATURES, N_PRODUCTS, predict_top3, predict_top3_simple
from .predictor import A2ProductRanker, predict_top3_products
from .training import train_ltr_model

__all__ = [
    "A2ProductRanker",
    "DEFAULT_MODEL_PATH",
    "FEATURE_COLUMNS",
    "N_FEATURES",
    "N_PRODUCTS",
    "predict_top3",
    "predict_top3_simple",
    "predict_top3_products",
    "train_ltr_model",
]
