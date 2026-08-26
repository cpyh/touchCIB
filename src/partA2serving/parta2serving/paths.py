from __future__ import annotations

import os
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SEED = 42


def _detect_data_dir() -> Path:
    env = os.environ.get("PARTA2_DATA_DIR")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    candidates = [
        PKG_ROOT / "data",
        PKG_ROOT.parent / "student_pkg" / "student_pkg" / "data",
        PKG_ROOT.parent / "data",
    ]
    for p in candidates:
        if (p / "t_customer.csv").exists():
            return p
    return PKG_ROOT / "data"


DATA_DIR = _detect_data_dir()
DATA_ROOT = DATA_DIR.parent
STRATEGY_CUSTOMERS = DATA_ROOT / "partA_strategy_customers.csv"
MODEL_DIR = PKG_ROOT / "models"
OUTPUT_DIR = PKG_ROOT / "outputs"
