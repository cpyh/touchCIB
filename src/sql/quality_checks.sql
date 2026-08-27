-- ODS data quality checks for the bundled source dataset.
-- Every row in the result should have status = PASS.
-- Change the schema below if DB_NAME in .env is not "cib".

USE `cib`;

WITH checks AS (
    SELECT 10 AS sort_order, 'row_count' AS category,
           'ods_customer contains at least 8000 bundled customers' AS check_name,
           0 AS expected_value,
           CASE WHEN COUNT(*) >= 8000 THEN 0 ELSE 1 END AS actual_value
    FROM ods_customer

    UNION ALL
    SELECT 20, 'row_count', 'ods_product has 30 rows', 30, COUNT(*)
    FROM ods_product

    UNION ALL
    SELECT 30, 'row_count', 'ods_holding has 8579 rows', 8579, COUNT(*)
    FROM ods_holding

    UNION ALL
    SELECT 40, 'row_count', 'ods_campaign has 50000 rows', 50000, COUNT(*)
    FROM ods_campaign

    UNION ALL
    SELECT 50, 'row_count', 'ods_event has 13142 rows', 13142, COUNT(*)
    FROM ods_event

    UNION ALL
    SELECT 60, 'completeness', 'required text fields are not empty', 0,
           (SELECT COUNT(*) FROM ods_customer
            WHERE TRIM(customer_id) = ''
               OR TRIM(age_group) = ''
               OR TRIM(city) = ''
               OR TRIM(occupation) = ''
               OR TRIM(income_level) = ''
               OR TRIM(risk_appetite) = ''
               OR TRIM(vip_level) = '')
         + (SELECT COUNT(*) FROM ods_product
            WHERE TRIM(product_id) = ''
               OR TRIM(product_name) = ''
               OR TRIM(product_type) = ''
               OR TRIM(risk_level) = ''
               OR TRIM(liquidity) = '')
         + (SELECT COUNT(*) FROM ods_holding
            WHERE TRIM(holding_id) = ''
               OR TRIM(customer_id) = ''
               OR TRIM(product_id) = '')
         + (SELECT COUNT(*) FROM ods_campaign
            WHERE TRIM(contact_id) = ''
               OR TRIM(customer_id) = ''
               OR TRIM(product_id) = ''
               OR TRIM(channel) = '')
         + (SELECT COUNT(*) FROM ods_event
            WHERE TRIM(event_id) = ''
               OR TRIM(customer_id) = ''
               OR TRIM(event_type) = '')

    UNION ALL
    SELECT 70, 'batch', 'etl_batch_id is not empty', 0,
           (SELECT COUNT(*) FROM ods_customer WHERE TRIM(etl_batch_id) = '')
         + (SELECT COUNT(*) FROM ods_product WHERE TRIM(etl_batch_id) = '')
         + (SELECT COUNT(*) FROM ods_holding WHERE TRIM(etl_batch_id) = '')
         + (SELECT COUNT(*) FROM ods_campaign WHERE TRIM(etl_batch_id) = '')
         + (SELECT COUNT(*) FROM ods_event WHERE TRIM(etl_batch_id) = '')

    UNION ALL
    SELECT 80, 'batch', 'bundled ETL batch exists in all ODS tables', 5,
           COUNT(DISTINCT source_table)
    FROM (
        SELECT 'ods_customer' AS source_table FROM ods_customer
        WHERE etl_batch_id = 'student_pkg_20260331'
        UNION ALL
        SELECT 'ods_product' FROM ods_product
        WHERE etl_batch_id = 'student_pkg_20260331'
        UNION ALL
        SELECT 'ods_holding' FROM ods_holding
        WHERE etl_batch_id = 'student_pkg_20260331'
        UNION ALL
        SELECT 'ods_campaign' FROM ods_campaign
        WHERE etl_batch_id = 'student_pkg_20260331'
        UNION ALL
        SELECT 'ods_event' FROM ods_event
        WHERE etl_batch_id = 'student_pkg_20260331'
    ) AS all_batches

    UNION ALL
    SELECT 90, 'domain', 'customer risk_appetite is R1-R5', 0, COUNT(*)
    FROM ods_customer
    WHERE risk_appetite NOT IN ('R1', 'R2', 'R3', 'R4', 'R5')

    UNION ALL
    SELECT 100, 'domain', 'customer has_app is 0 or 1', 0, COUNT(*)
    FROM ods_customer
    WHERE has_app NOT IN (0, 1)

    UNION ALL
    SELECT 110, 'domain', 'customer age_group is recognized', 0, COUNT(*)
    FROM ods_customer
    WHERE age_group NOT IN ('18-24', '25-34', '35-44', '45-54', '55-64', '65+')

    UNION ALL
    SELECT 120, 'domain', 'customer vip_level is recognized', 0, COUNT(*)
    FROM ods_customer
    WHERE vip_level NOT IN ('普通', '银卡', '金卡', '钻石')

    UNION ALL
    SELECT 130, 'domain', 'product risk_level is R1-R5', 0, COUNT(*)
    FROM ods_product
    WHERE risk_level NOT IN ('R1', 'R2', 'R3', 'R4', 'R5')

    UNION ALL
    SELECT 140, 'domain', 'product type is recognized', 0, COUNT(*)
    FROM ods_product
    WHERE product_type NOT IN ('固定期限', '定开', '混合', '现金管理')

    UNION ALL
    SELECT 150, 'domain', 'product liquidity is recognized', 0, COUNT(*)
    FROM ods_product
    WHERE liquidity NOT IN ('T+0', 'T+1', '封闭')

    UNION ALL
    SELECT 160, 'domain', 'campaign responded is 0 or 1', 0, COUNT(*)
    FROM ods_campaign
    WHERE responded NOT IN (0, 1)

    UNION ALL
    SELECT 170, 'domain', 'campaign channel is recognized', 0, COUNT(*)
    FROM ods_campaign
    WHERE channel NOT IN ('app_push', 'call', 'manager', 'sms')

    UNION ALL
    SELECT 180, 'domain', 'event type is recognized', 0, COUNT(*)
    FROM ods_event
    WHERE event_type NOT IN ('complaint', 'consult', 'login')

    UNION ALL
    SELECT 190, 'numeric', 'customer AUM is non-negative', 0, COUNT(*)
    FROM ods_customer
    WHERE aum < 0

    UNION ALL
    SELECT 200, 'numeric', 'product numeric values are non-negative', 0, COUNT(*)
    FROM ods_product
    WHERE volatility < 0 OR min_invest < 0

    UNION ALL
    SELECT 210, 'numeric', 'holding amount is positive', 0, COUNT(*)
    FROM ods_holding
    WHERE amount <= 0

    UNION ALL
    SELECT 220, 'date', 'business dates are not in the future', 0,
           (SELECT COUNT(*) FROM ods_customer WHERE register_date > CURRENT_DATE)
         + (SELECT COUNT(*) FROM ods_product WHERE launch_date > CURRENT_DATE)
         + (SELECT COUNT(*) FROM ods_holding WHERE buy_date > CURRENT_DATE)
         + (SELECT COUNT(*) FROM ods_campaign WHERE contact_date > CURRENT_DATE)
         + (SELECT COUNT(*) FROM ods_event WHERE event_date > CURRENT_DATE)

    UNION ALL
    SELECT 230, 'relationship', 'holding customers exist', 0, COUNT(*)
    FROM ods_holding AS h
    LEFT JOIN ods_customer AS c ON c.customer_id = h.customer_id
    WHERE c.customer_id IS NULL

    UNION ALL
    SELECT 240, 'relationship', 'holding products exist', 0, COUNT(*)
    FROM ods_holding AS h
    LEFT JOIN ods_product AS p ON p.product_id = h.product_id
    WHERE p.product_id IS NULL

    UNION ALL
    SELECT 250, 'relationship', 'campaign customers exist', 0, COUNT(*)
    FROM ods_campaign AS m
    LEFT JOIN ods_customer AS c ON c.customer_id = m.customer_id
    WHERE c.customer_id IS NULL

    UNION ALL
    SELECT 260, 'relationship', 'campaign products exist', 0, COUNT(*)
    FROM ods_campaign AS m
    LEFT JOIN ods_product AS p ON p.product_id = m.product_id
    WHERE p.product_id IS NULL

    UNION ALL
    SELECT 270, 'relationship', 'event customers exist', 0, COUNT(*)
    FROM ods_event AS e
    LEFT JOIN ods_customer AS c ON c.customer_id = e.customer_id
    WHERE c.customer_id IS NULL

    UNION ALL
    SELECT 280, 'chronology', 'holdings occur after customer registration', 0, COUNT(*)
    FROM ods_holding AS h
    JOIN ods_customer AS c ON c.customer_id = h.customer_id
    WHERE h.buy_date < c.register_date

    UNION ALL
    SELECT 290, 'chronology', 'holdings occur after product launch', 0, COUNT(*)
    FROM ods_holding AS h
    JOIN ods_product AS p ON p.product_id = h.product_id
    WHERE h.buy_date < p.launch_date

    UNION ALL
    SELECT 300, 'chronology', 'campaigns occur after customer registration', 0, COUNT(*)
    FROM ods_campaign AS m
    JOIN ods_customer AS c ON c.customer_id = m.customer_id
    WHERE m.contact_date < c.register_date

    UNION ALL
    SELECT 310, 'chronology', 'campaigns occur after product launch', 0, COUNT(*)
    FROM ods_campaign AS m
    JOIN ods_product AS p ON p.product_id = m.product_id
    WHERE m.contact_date < p.launch_date

    UNION ALL
    SELECT 320, 'chronology', 'events occur after customer registration', 0, COUNT(*)
    FROM ods_event AS e
    JOIN ods_customer AS c ON c.customer_id = e.customer_id
    WHERE e.event_date < c.register_date

    UNION ALL
    SELECT 330, 'dwd', 'DWD customer count matches ODS',
           (SELECT COUNT(*) FROM ods_customer), COUNT(*)
    FROM dwd_dim_customer

    UNION ALL
    SELECT 340, 'dwd', 'DWD product count matches ODS',
           (SELECT COUNT(*) FROM ods_product), COUNT(*)
    FROM dwd_dim_product

    UNION ALL
    SELECT 350, 'dwd', 'DWD holding count matches ODS',
           (SELECT COUNT(*) FROM ods_holding), COUNT(*)
    FROM dwd_fact_holding

    UNION ALL
    SELECT 360, 'dwd', 'DWD campaign count matches ODS',
           (SELECT COUNT(*) FROM ods_campaign), COUNT(*)
    FROM dwd_fact_campaign

    UNION ALL
    SELECT 370, 'dwd', 'DWD event count matches ODS',
           (SELECT COUNT(*) FROM ods_event), COUNT(*)
    FROM dwd_fact_event

    UNION ALL
    SELECT 380, 'dwd_relationship', 'DWD fact customers exist', 0,
           (SELECT COUNT(*)
            FROM dwd_fact_holding AS h
            LEFT JOIN dwd_dim_customer AS c ON c.customer_id = h.customer_id
            WHERE c.customer_id IS NULL)
         + (SELECT COUNT(*)
            FROM dwd_fact_campaign AS m
            LEFT JOIN dwd_dim_customer AS c ON c.customer_id = m.customer_id
            WHERE c.customer_id IS NULL)
         + (SELECT COUNT(*)
            FROM dwd_fact_event AS e
            LEFT JOIN dwd_dim_customer AS c ON c.customer_id = e.customer_id
            WHERE c.customer_id IS NULL)

    UNION ALL
    SELECT 390, 'dwd_relationship', 'DWD fact products exist', 0,
           (SELECT COUNT(*)
            FROM dwd_fact_holding AS h
            LEFT JOIN dwd_dim_product AS p ON p.product_id = h.product_id
            WHERE p.product_id IS NULL)
         + (SELECT COUNT(*)
            FROM dwd_fact_campaign AS m
            LEFT JOIN dwd_dim_product AS p ON p.product_id = m.product_id
            WHERE p.product_id IS NULL)

    UNION ALL
    SELECT 400, 'snapshot', 'DWS covers every as-of eligible DWD customer',
           (SELECT COUNT(*) FROM dwd_dim_customer
            WHERE register_date <= '2026-03-31'), COUNT(*)
    FROM dws_customer_360

    UNION ALL
    SELECT 410, 'snapshot', 'DWS snapshot date is 2026-03-31', 0, COUNT(*)
    FROM dws_customer_360
    WHERE snapshot_date <> '2026-03-31'
)
SELECT category,
       check_name,
       CASE
           WHEN actual_value = expected_value THEN 'PASS'
           ELSE 'FAIL'
       END AS status,
       expected_value,
       actual_value
FROM checks
ORDER BY sort_order;
