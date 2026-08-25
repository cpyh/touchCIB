"""Shared, leakage-safe feature construction for Part A training and inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


FEATURE_VERSION = "a1_features_v1"
RISK_SCORE = {f"R{level}": level for level in range(1, 6)}

CATEGORICAL_FEATURES = [
    "age_group",
    "city",
    "occupation",
    "income_level",
    "risk_appetite",
    "vip_level",
    "product_id",
    "product_type",
    "product_risk_level",
    "liquidity",
    "channel",
    "contact_month",
    "contact_weekday",
    "product_channel",
    "risk_pair",
    "vip_channel",
]

NUMERIC_FEATURES = [
    "has_app",
    "aum_log",
    "expected_return",
    "volatility",
    "min_invest_log",
    "duration_days",
    "customer_tenure_days",
    "product_age_days",
    "risk_gap",
    "risk_compatible",
    "min_invest_aum_ratio",
    "has_app_channel_match",
    "holding_total_amount_log",
    "holding_product_count",
    "holding_record_count",
    "holds_target_product",
    "target_product_amount_log",
    "login_count_30d",
    "login_count_90d",
    "consult_count_30d",
    "consult_count_90d",
    "complaint_count_90d",
    "days_since_last_login",
    "days_since_last_event",
    "prior_contact_count",
    "prior_response_count",
    "prior_response_rate",
    "prior_channel_contact_count",
    "prior_channel_response_rate",
    "prior_product_contact_count",
    "prior_product_response_rate",
    "days_since_last_contact",
]

MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

EVIDENCE_FEATURES = [
    "risk_appetite",
    "product_risk_level",
    "risk_compatible",
    "risk_gap",
    "has_app",
    "has_app_channel_match",
    "holding_product_count",
    "holding_total_amount_log",
    "holds_target_product",
    "login_count_30d",
    "login_count_90d",
    "consult_count_90d",
    "complaint_count_90d",
    "prior_contact_count",
    "prior_response_rate",
]


def load_csv_sources(data_dir: Path) -> dict[str, pd.DataFrame]:
    """Load the five official business tables from a directory."""
    return {
        "customers": pd.read_csv(data_dir / "t_customer.csv", dtype={"customer_id": str}),
        "products": pd.read_csv(
            data_dir / "t_product.csv", dtype={"product_id": str}
        ),
        "holdings": pd.read_csv(
            data_dir / "t_holding.csv",
            dtype={"holding_id": str, "customer_id": str, "product_id": str},
        ),
        "campaigns": pd.read_csv(
            data_dir / "t_campaign.csv",
            dtype={"contact_id": str, "customer_id": str, "product_id": str},
        ),
        "events": pd.read_csv(
            data_dir / "t_event.csv",
            dtype={"event_id": str, "customer_id": str},
        ),
    }


def _prepare_sources(
    contacts: pd.DataFrame,
    customers: pd.DataFrame,
    products: pd.DataFrame,
    holdings: pd.DataFrame,
    events: pd.DataFrame,
    campaign_history: pd.DataFrame,
) -> tuple[pd.DataFrame, ...]:
    contacts = contacts.copy()
    customers = customers.copy()
    products = products.copy()
    holdings = holdings.copy()
    events = events.copy()
    campaign_history = campaign_history.copy()

    required_contact_columns = {
        "contact_id",
        "customer_id",
        "product_id",
        "channel",
        "contact_date",
    }
    missing = required_contact_columns - set(contacts.columns)
    if missing:
        raise ValueError(f"contacts is missing columns: {sorted(missing)}")
    if contacts["contact_id"].duplicated().any():
        raise ValueError("contacts contains duplicate contact_id values")

    contacts["contact_date"] = pd.to_datetime(
        contacts["contact_date"], errors="raise"
    ).dt.normalize()
    customers["register_date"] = pd.to_datetime(
        customers["register_date"], errors="raise"
    ).dt.normalize()
    products["launch_date"] = pd.to_datetime(
        products["launch_date"], errors="raise"
    ).dt.normalize()
    holdings["buy_date"] = pd.to_datetime(
        holdings["buy_date"], errors="raise"
    ).dt.normalize()
    events["event_date"] = pd.to_datetime(
        events["event_date"], errors="raise"
    ).dt.normalize()
    campaign_history["contact_date"] = pd.to_datetime(
        campaign_history["contact_date"], errors="raise"
    ).dt.normalize()

    for frame, columns in (
        (customers, ["aum", "has_app"]),
        (
            products,
            [
                "expected_return",
                "volatility",
                "min_invest",
                "duration_days",
            ],
        ),
        (holdings, ["amount"]),
        (campaign_history, ["responded"]),
    ):
        for column in columns:
            frame[column] = pd.to_numeric(frame[column], errors="raise")

    return contacts, customers, products, holdings, events, campaign_history


def _holding_features(
    contacts: pd.DataFrame,
    holdings: pd.DataFrame,
) -> pd.DataFrame:
    links = contacts[
        ["__row_id", "customer_id", "product_id", "contact_date"]
    ].rename(columns={"product_id": "target_product_id"}).merge(
        holdings.rename(columns={"product_id": "held_product_id"}),
        on="customer_id",
        how="left",
    )
    valid = links[
        links["buy_date"].notna() & (links["buy_date"] < links["contact_date"])
    ].copy()
    if valid.empty:
        return pd.DataFrame(columns=["__row_id"])

    totals = valid.groupby("__row_id", sort=False).agg(
        holding_total_amount=("amount", "sum"),
        holding_product_count=("held_product_id", "nunique"),
        holding_record_count=("held_product_id", "size"),
    )
    target = valid[valid["target_product_id"] == valid["held_product_id"]]
    target_totals = target.groupby("__row_id", sort=False).agg(
        target_product_amount=("amount", "sum")
    )
    result = totals.join(target_totals, how="left").reset_index()
    result["target_product_amount"] = result["target_product_amount"].fillna(0.0)
    result["holds_target_product"] = (
        result["target_product_amount"] > 0
    ).astype(int)
    return result


def _event_features(
    contacts: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:
    links = contacts[["__row_id", "customer_id", "contact_date"]].merge(
        events, on="customer_id", how="left"
    )
    links["days_before_contact"] = (
        links["contact_date"] - links["event_date"]
    ).dt.days
    valid = links[links["days_before_contact"] > 0].copy()
    if valid.empty:
        return pd.DataFrame(columns=["__row_id"])

    definitions = {
        "login_count_30d": ("login", 30),
        "login_count_90d": ("login", 90),
        "consult_count_30d": ("consult", 30),
        "consult_count_90d": ("consult", 90),
        "complaint_count_90d": ("complaint", 90),
    }
    for name, (event_type, window_days) in definitions.items():
        valid[name] = (
            (valid["event_type"] == event_type)
            & (valid["days_before_contact"] <= window_days)
        ).astype(int)

    result = (
        valid.groupby("__row_id", sort=False)[list(definitions)]
        .sum()
        .reset_index()
    )
    last_event = valid.groupby("__row_id", sort=False)["days_before_contact"].min()
    last_login = (
        valid[valid["event_type"] == "login"]
        .groupby("__row_id", sort=False)["days_before_contact"]
        .min()
    )
    result = result.merge(
        last_event.rename("days_since_last_event"), on="__row_id", how="left"
    ).merge(
        last_login.rename("days_since_last_login"), on="__row_id", how="left"
    )
    return result


def _campaign_history_features(
    contacts: pd.DataFrame,
    campaign_history: pd.DataFrame,
) -> pd.DataFrame:
    history = campaign_history[
        ["customer_id", "product_id", "channel", "contact_date", "responded"]
    ].rename(
        columns={
            "product_id": "history_product_id",
            "channel": "history_channel",
            "contact_date": "history_contact_date",
        }
    )
    links = contacts[
        ["__row_id", "customer_id", "product_id", "channel", "contact_date"]
    ].merge(history, on="customer_id", how="left")
    valid = links[
        links["history_contact_date"].notna()
        & (links["history_contact_date"] < links["contact_date"])
    ].copy()
    if valid.empty:
        return pd.DataFrame(columns=["__row_id"])

    valid["days_before_contact"] = (
        valid["contact_date"] - valid["history_contact_date"]
    ).dt.days
    totals = valid.groupby("__row_id", sort=False).agg(
        prior_contact_count=("responded", "size"),
        prior_response_count=("responded", "sum"),
        days_since_last_contact=("days_before_contact", "min"),
    )

    same_channel = valid[valid["channel"] == valid["history_channel"]]
    channel_totals = same_channel.groupby("__row_id", sort=False).agg(
        prior_channel_contact_count=("responded", "size"),
        prior_channel_response_count=("responded", "sum"),
    )

    same_product = valid[valid["product_id"] == valid["history_product_id"]]
    product_totals = same_product.groupby("__row_id", sort=False).agg(
        prior_product_contact_count=("responded", "size"),
        prior_product_response_count=("responded", "sum"),
    )
    return totals.join(channel_totals, how="left").join(
        product_totals, how="left"
    ).reset_index()


def _smoothed_rate(successes: pd.Series, count: pd.Series) -> pd.Series:
    """Beta(2, 8) smoothing gives a neutral 20% prior without future labels."""
    return (successes + 2.0) / (count + 10.0)


def build_contact_features(
    contacts: pd.DataFrame,
    *,
    customers: pd.DataFrame,
    products: pd.DataFrame,
    holdings: pd.DataFrame,
    events: pd.DataFrame,
    campaign_history: pd.DataFrame,
) -> pd.DataFrame:
    """Build one feature row per contact using strictly earlier facts only."""
    (
        contacts,
        customers,
        products,
        holdings,
        events,
        campaign_history,
    ) = _prepare_sources(
        contacts,
        customers,
        products,
        holdings,
        events,
        campaign_history,
    )
    contacts["__row_id"] = np.arange(len(contacts), dtype=int)

    product_columns = products.rename(
        columns={"risk_level": "product_risk_level"}
    )
    result = contacts.merge(
        customers, on="customer_id", how="left", validate="many_to_one"
    ).merge(
        product_columns, on="product_id", how="left", validate="many_to_one"
    )
    if result["register_date"].isna().any():
        missing = result.loc[result["register_date"].isna(), "customer_id"].unique()
        raise ValueError(f"unknown customer_id values: {missing[:5].tolist()}")
    if result["launch_date"].isna().any():
        missing = result.loc[result["launch_date"].isna(), "product_id"].unique()
        raise ValueError(f"unknown product_id values: {missing[:5].tolist()}")

    for feature_frame in (
        _holding_features(contacts, holdings),
        _event_features(contacts, events),
        _campaign_history_features(contacts, campaign_history),
    ):
        result = result.merge(feature_frame, on="__row_id", how="left")

    zero_columns = [
        "holding_total_amount",
        "holding_product_count",
        "holding_record_count",
        "target_product_amount",
        "holds_target_product",
        "login_count_30d",
        "login_count_90d",
        "consult_count_30d",
        "consult_count_90d",
        "complaint_count_90d",
        "prior_contact_count",
        "prior_response_count",
        "prior_channel_contact_count",
        "prior_channel_response_count",
        "prior_product_contact_count",
        "prior_product_response_count",
    ]
    for column in zero_columns:
        if column not in result:
            result[column] = 0.0
        result[column] = result[column].fillna(0.0)

    result["prior_response_rate"] = _smoothed_rate(
        result["prior_response_count"], result["prior_contact_count"]
    )
    result["prior_channel_response_rate"] = _smoothed_rate(
        result["prior_channel_response_count"],
        result["prior_channel_contact_count"],
    )
    result["prior_product_response_rate"] = _smoothed_rate(
        result["prior_product_response_count"],
        result["prior_product_contact_count"],
    )

    customer_risk = result["risk_appetite"].map(RISK_SCORE)
    product_risk = result["product_risk_level"].map(RISK_SCORE)
    if customer_risk.isna().any() or product_risk.isna().any():
        raise ValueError("risk level must be one of R1-R5")

    result["aum_log"] = np.log1p(result["aum"].clip(lower=0))
    result["min_invest_log"] = np.log1p(result["min_invest"].clip(lower=0))
    result["holding_total_amount_log"] = np.log1p(
        result["holding_total_amount"].clip(lower=0)
    )
    result["target_product_amount_log"] = np.log1p(
        result["target_product_amount"].clip(lower=0)
    )
    result["customer_tenure_days"] = (
        result["contact_date"] - result["register_date"]
    ).dt.days.clip(lower=0)
    result["product_age_days"] = (
        result["contact_date"] - result["launch_date"]
    ).dt.days.clip(lower=0)
    result["risk_gap"] = customer_risk - product_risk
    result["risk_compatible"] = (result["risk_gap"] >= 0).astype(int)
    result["min_invest_aum_ratio"] = (
        result["min_invest"] / result["aum"].clip(lower=1.0)
    ).clip(upper=10.0)
    result["has_app_channel_match"] = (
        (result["has_app"] == 1) & (result["channel"] == "app_push")
    ).astype(int)

    result["contact_month"] = result["contact_date"].dt.month.astype(str)
    result["contact_weekday"] = result["contact_date"].dt.weekday.astype(str)
    result["product_channel"] = result["product_id"] + "__" + result["channel"]
    result["risk_pair"] = (
        result["risk_appetite"] + "__" + result["product_risk_level"]
    )
    result["vip_channel"] = result["vip_level"] + "__" + result["channel"]

    missing_features = set(MODEL_FEATURES) - set(result.columns)
    if missing_features:
        raise RuntimeError(f"feature construction missed: {sorted(missing_features)}")

    return result.sort_values("__row_id").reset_index(drop=True)
