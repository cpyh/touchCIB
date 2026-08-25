-- Fully rebuild the standardized DWD dimensions and facts from ODS.
-- The caller must select the target database before executing this file.

DELETE FROM dwd_fact_holding;
DELETE FROM dwd_fact_campaign;
DELETE FROM dwd_fact_event;
DELETE FROM dwd_dim_customer;
DELETE FROM dwd_dim_product;

INSERT INTO dwd_dim_customer (
    customer_id,
    age_group,
    city,
    occupation,
    income_level,
    register_date,
    aum,
    risk_appetite,
    vip_level,
    has_app,
    source_batch_id
)
SELECT
    customer_id,
    age_group,
    city,
    occupation,
    income_level,
    register_date,
    aum,
    risk_appetite,
    vip_level,
    has_app,
    etl_batch_id
FROM ods_customer;

INSERT INTO dwd_dim_product (
    product_id,
    product_name,
    product_type,
    risk_level,
    expected_return,
    volatility,
    min_invest,
    duration_days,
    liquidity,
    launch_date,
    source_batch_id
)
SELECT
    product_id,
    product_name,
    product_type,
    risk_level,
    expected_return,
    volatility,
    min_invest,
    duration_days,
    liquidity,
    launch_date,
    etl_batch_id
FROM ods_product;

INSERT INTO dwd_fact_holding (
    holding_id,
    customer_id,
    product_id,
    amount,
    buy_date,
    source_batch_id
)
SELECT
    holding_id,
    customer_id,
    product_id,
    amount,
    buy_date,
    etl_batch_id
FROM ods_holding;

INSERT INTO dwd_fact_campaign (
    contact_id,
    customer_id,
    product_id,
    channel,
    contact_date,
    responded,
    source_batch_id
)
SELECT
    contact_id,
    customer_id,
    product_id,
    channel,
    contact_date,
    responded,
    etl_batch_id
FROM ods_campaign;

INSERT INTO dwd_fact_event (
    event_id,
    customer_id,
    event_type,
    event_date,
    source_batch_id
)
SELECT
    event_id,
    customer_id,
    event_type,
    event_date,
    etl_batch_id
FROM ods_event;
