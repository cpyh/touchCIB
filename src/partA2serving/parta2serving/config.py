from __future__ import annotations

from .paths import DATA_DIR, MODEL_DIR, OUTPUT_DIR, SEED, STRATEGY_CUSTOMERS

RANDOM_STATE = SEED
VALID_CHANNELS = ("sms", "call", "app_push", "manager")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MODEL_PATH = MODEL_DIR / "ltr_nextbuy_lightgbm_prod.joblib"
STRATEGY_ASOF = "2026-04-15"
LABEL_MODE = "L2"
CHANNELS = list(VALID_CHANNELS)

EVAL_FEATURE_CUTOFF = "2025-10-01"
EVAL_LABEL_CUTOFF = "2026-01-01"
