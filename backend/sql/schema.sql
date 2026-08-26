CREATE DATABASE IF NOT EXISTS touch_cib
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE touch_cib;

CREATE TABLE IF NOT EXISTS t_customer (
    customer_id VARCHAR(32) NOT NULL,
    age_group VARCHAR(16) NOT NULL,
    city VARCHAR(50) NOT NULL,
    occupation VARCHAR(32) NOT NULL,
    income_level VARCHAR(16) NOT NULL,
    register_date DATE NOT NULL,
    aum DECIMAL(18,2) NOT NULL DEFAULT 0,
    risk_appetite CHAR(2) NOT NULL,
    vip_level VARCHAR(16) NOT NULL,
    has_app TINYINT(1) NOT NULL DEFAULT 0,
    ai_summary TEXT NULL,
    ai_summary_generated_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (customer_id),
    INDEX idx_customer_risk_vip (risk_appetite, vip_level),
    INDEX idx_customer_city (city),
    CONSTRAINT chk_customer_aum CHECK (aum >= 0),
    CONSTRAINT chk_customer_risk CHECK (risk_appetite IN ('R1','R2','R3','R4','R5')),
    CONSTRAINT chk_customer_has_app CHECK (has_app IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_product (
    product_id VARCHAR(32) NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    product_type VARCHAR(32) NOT NULL,
    risk_level CHAR(2) NOT NULL,
    expected_return DECIMAL(10,6) NOT NULL,
    volatility DECIMAL(10,6) NOT NULL,
    min_invest DECIMAL(18,2) NOT NULL,
    duration_days INT UNSIGNED NOT NULL,
    liquidity VARCHAR(16) NOT NULL,
    launch_date DATE NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (product_id),
    INDEX idx_product_type_risk (product_type, risk_level),
    CONSTRAINT chk_product_risk CHECK (risk_level IN ('R1','R2','R3','R4','R5')),
    CONSTRAINT chk_product_volatility CHECK (volatility >= 0),
    CONSTRAINT chk_product_min_invest CHECK (min_invest >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_holding (
    holding_id VARCHAR(32) NOT NULL,
    customer_id VARCHAR(32) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    amount DECIMAL(18,2) NOT NULL,
    buy_date DATE NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (holding_id),
    INDEX idx_holding_customer (customer_id),
    INDEX idx_holding_product (product_id),
    INDEX idx_holding_customer_buy_date (customer_id, buy_date),
    CONSTRAINT fk_holding_customer FOREIGN KEY (customer_id)
        REFERENCES t_customer (customer_id),
    CONSTRAINT fk_holding_product FOREIGN KEY (product_id)
        REFERENCES t_product (product_id),
    CONSTRAINT chk_holding_amount CHECK (amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_event (
    event_id VARCHAR(32) NOT NULL,
    customer_id VARCHAR(32) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    event_date DATE NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (event_id),
    INDEX idx_event_customer_date (customer_id, event_date),
    INDEX idx_event_type_date (event_type, event_date),
    CONSTRAINT fk_event_customer FOREIGN KEY (customer_id)
        REFERENCES t_customer (customer_id),
    CONSTRAINT chk_event_type CHECK (event_type IN ('login','consult','complaint'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
