from __future__ import annotations

import pandas as pd


def top3_from_scores(scores: pd.DataFrame) -> pd.DataFrame:
    ranked = (
        scores.sort_values(["customer_id", "score"], ascending=[True, False])
        .groupby("customer_id", group_keys=False)
        .head(3)
        .copy()
    )
    ranked["rank"] = ranked.groupby("customer_id").cumcount() + 1
    return ranked
