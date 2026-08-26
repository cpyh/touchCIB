from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DATA_DIR, LABEL_MODE, STRATEGY_CUSTOMERS
from .labels import LabelMode, make_label_table


def load_tables(data_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    root = Path(data_dir) if data_dir else DATA_DIR
    cust = pd.read_csv(root / "t_customer.csv")
    prod = pd.read_csv(root / "t_product.csv")
    hold = pd.read_csv(root / "t_holding.csv")
    camp = pd.read_csv(root / "t_campaign.csv")
    event = pd.read_csv(root / "t_event.csv")

    hold["buy_date"] = pd.to_datetime(hold["buy_date"])
    camp["contact_date"] = pd.to_datetime(camp["contact_date"])
    event["event_date"] = pd.to_datetime(event["event_date"])
    cust["register_date"] = pd.to_datetime(cust["register_date"])
    prod["launch_date"] = pd.to_datetime(prod["launch_date"])

    risk_map = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
    cust = cust.copy()
    prod = prod.copy()
    cust["risk_n"] = cust["risk_appetite"].map(risk_map).astype(int)
    prod["risk_n"] = prod["risk_level"].map(risk_map).astype(int)
    prod["liq_n"] = (
        prod["liquidity"]
        .astype(str)
        .map(lambda x: 2 if "T+0" in x else (1 if "T+1" in x else 0))
        .astype(int)
    )
    return {
        "customer": cust,
        "product": prod,
        "holding": hold,
        "campaign": camp,
        "event": event,
    }


def load_strategy_customers(path: Path | None = None) -> pd.DataFrame:
    sc = pd.read_csv(path or STRATEGY_CUSTOMERS)
    sc["strategy_date"] = pd.to_datetime(sc["strategy_date"])
    return sc


def filter_as_of(tables: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    return {
        "customer": tables["customer"],
        "product": tables["product"],
        "holding": tables["holding"].loc[tables["holding"]["buy_date"] < as_of].copy(),
        "campaign": tables["campaign"].loc[tables["campaign"]["contact_date"] < as_of].copy(),
        "event": tables["event"].loc[tables["event"]["event_date"] < as_of].copy(),
    }


def make_eval_split(
    campaign: pd.DataFrame,
    feature_cutoff: pd.Timestamp,
    label_cutoff: pd.Timestamp,
    holding: pd.DataFrame | None = None,
    label_mode: LabelMode | str = LABEL_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    防泄漏切分：
    - 特征只使用 < feature_cutoff 的历史
    - 训练集：feature_cutoff <= contact_date < label_cutoff
    - 评测标签：由 label_mode 决定（默认 L2 首次新持仓）
    """
    train_camp = campaign.loc[
        (campaign["contact_date"] >= feature_cutoff)
        & (campaign["contact_date"] < label_cutoff)
    ].copy()
    if holding is None:
        holding = pd.DataFrame(columns=["customer_id", "product_id", "buy_date", "holding_id"])
    labels = make_label_table(campaign, holding, label_cutoff, label_mode)
    return train_camp, labels
