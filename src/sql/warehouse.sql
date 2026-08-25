-- Rebuild the physical customer profile table from the standardized DWD layer.
-- The caller must select the target database before executing this file.

DROP TABLE IF EXISTS dws_customer_360;

CREATE TABLE dws_customer_360
ENGINE=InnoDB
COMMENT='客户全景画像表'
AS
SELECT
    c.customer_id,
    CAST('2026-03-31' AS DATE) AS snapshot_date,
    c.age_group,
    c.city,
    c.occupation,
    c.income_level,
    c.register_date,
    c.aum,
    c.risk_appetite,
    c.vip_level,
    c.has_app,
    COALESCE(h.holding_product_count, 0) AS holding_product_count,
    COALESCE(h.holding_amount, 0.00) AS holding_amount,
    h.last_buy_date,
    COALESCE(e.event_count, 0) AS event_count,
    COALESCE(e.login_count, 0) AS login_count,
    COALESCE(e.consult_count, 0) AS consult_count,
    COALESCE(e.complaint_count, 0) AS complaint_count,
    e.last_event_date,
    COALESCE(m.campaign_count, 0) AS campaign_count,
    COALESCE(m.response_count, 0) AS response_count,
    COALESCE(m.response_rate, 0.000000) AS response_rate,
    m.last_contact_date
FROM dwd_dim_customer AS c
LEFT JOIN (
    SELECT
        customer_id,
        COUNT(DISTINCT product_id) AS holding_product_count,
        SUM(amount) AS holding_amount,
        MAX(buy_date) AS last_buy_date
    FROM dwd_fact_holding
    WHERE buy_date <= '2026-03-31'
    GROUP BY customer_id
) AS h ON h.customer_id = c.customer_id
LEFT JOIN (
    SELECT
        customer_id,
        COUNT(*) AS event_count,
        SUM(event_type = 'login') AS login_count,
        SUM(event_type = 'consult') AS consult_count,
        SUM(event_type = 'complaint') AS complaint_count,
        MAX(event_date) AS last_event_date
    FROM dwd_fact_event
    WHERE event_date <= '2026-03-31'
    GROUP BY customer_id
) AS e ON e.customer_id = c.customer_id
LEFT JOIN (
    SELECT
        customer_id,
        COUNT(*) AS campaign_count,
        SUM(responded) AS response_count,
        ROUND(AVG(responded), 6) AS response_rate,
        MAX(contact_date) AS last_contact_date
    FROM dwd_fact_campaign
    WHERE contact_date <= '2026-03-31'
    GROUP BY customer_id
) AS m ON m.customer_id = c.customer_id
WHERE c.register_date <= '2026-03-31';

ALTER TABLE dws_customer_360
    ADD PRIMARY KEY (customer_id);
