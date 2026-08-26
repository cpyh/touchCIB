"""A2 LTR 训练数据构造与模型训练。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DEFAULT_MODEL_PATH, LABEL_MODE, SEED
from .data import filter_as_of, load_tables, make_eval_split
from .features import attach_pair_features, build_feature_context
from .models import ListwiseRanker

DEFAULT_TRAIN_WINDOWS: list[tuple[str, str]] = [
    ("2025-10-01", "2026-01-01"),
    ("2025-07-01", "2025-10-01"),
    ("2025-04-01", "2025-07-01"),
]

DEFAULT_LTR_MODEL_PATH = DEFAULT_MODEL_PATH


def ctx_from_asof(tables: dict, as_of: str | pd.Timestamp) -> tuple[dict, dict]:
    as_of_ts = pd.Timestamp(as_of)
    snapped = filter_as_of(tables, as_of_ts)
    ctx = build_feature_context(
        snapped["customer"],
        snapped["product"],
        snapped["holding"],
        snapped["campaign"],
        snapped["event"],
    )
    return ctx, snapped


def build_nextbuy_rank_frame(
    tables: dict,
    feature_cutoff: pd.Timestamp,
    label_cutoff: pd.Timestamp,
    seed: int = 42,
    label_mode: str = LABEL_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _, labels = make_eval_split(
        tables["campaign"],
        feature_cutoff,
        label_cutoff,
        tables["holding"],
        label_mode,
    )
    ctx, _ = ctx_from_asof(tables, feature_cutoff)
    products = tables["product"]["product_id"].tolist()
    rows: list[tuple] = []
    for r in labels.itertuples(index=False):
        for pid in products:
            rel = 3 if pid == r.label_product else 0
            rows.append((r.customer_id, pid, "manager", rel))
    base = pd.DataFrame(
        rows, columns=["customer_id", "product_id", "channel", "relevance"]
    )
    if base.empty:
        return base, labels
    base = base.sample(frac=1.0, random_state=seed).sort_values("customer_id")
    base = base.reset_index(drop=True)
    feat = attach_pair_features(base.drop(columns=["relevance"]), ctx)
    feat["relevance"] = base["relevance"].to_numpy()
    return feat, labels


def collect_rank_frames(
    tables: dict,
    windows: list[tuple[str, str]] | None = None,
    seed: int = SEED,
    label_mode: str = LABEL_MODE,
) -> pd.DataFrame:
    windows = windows or DEFAULT_TRAIN_WINDOWS
    frames: list[pd.DataFrame] = []
    for i, (feat_c, lab_c) in enumerate(windows):
        fr, _ = build_nextbuy_rank_frame(
            tables,
            pd.Timestamp(feat_c),
            pd.Timestamp(lab_c),
            seed=seed + i,
            label_mode=label_mode,
        )
        if len(fr):
            fr = fr.copy()
            fr["customer_id"] = fr["customer_id"].astype(str) + f"__w{i}"
            frames.append(fr)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def train_ltr_model(
    *,
    model_path: str | Path | None = None,
    train_windows: list[tuple[str, str]] | None = None,
    tables: dict | None = None,
    backend: str = "lightgbm",
) -> tuple[ListwiseRanker, dict]:
    """训练 LGBMRanker 并保存到 model_path（默认 outputs/a2/models/ltr_nextbuy_lightgbm_prod.joblib）。"""
    from pathlib import Path

    path = Path(model_path) if model_path else DEFAULT_LTR_MODEL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tables = tables or load_tables()
    rank_frame = collect_rank_frames(tables, train_windows)
    if rank_frame.empty:
        raise RuntimeError("训练样本为空，无法训练 LTR 模型")

    model = ListwiseRanker(backend=backend)
    fit_meta = model.fit(rank_frame)
    model.save(path)
    meta = {
        "model_path": str(path),
        "backend": backend,
        "label_mode": LABEL_MODE,
        "train_windows": train_windows or DEFAULT_TRAIN_WINDOWS,
        "n_rank_rows": int(len(rank_frame)),
        "fit": fit_meta,
    }
    return model, meta
