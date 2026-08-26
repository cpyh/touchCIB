CREATE TABLE IF NOT EXISTS ods_customer (
    customer_id     VARCHAR(64)    NOT NULL COMMENT '客户唯一标识',
    age_group       VARCHAR(16)    NOT NULL COMMENT '年龄段',
    city            VARCHAR(32)    NOT NULL COMMENT '城市',
    occupation      VARCHAR(32)    NOT NULL COMMENT '职业',
    income_level    VARCHAR(32)    NOT NULL COMMENT '收入区间',
    register_date   DATE           NOT NULL COMMENT '注册日期',
    aum             DECIMAL(18, 2) NOT NULL COMMENT '资产管理规模（元）',
    risk_appetite   CHAR(2)        NOT NULL COMMENT '风险偏好 R1-R5',
    vip_level       VARCHAR(16)    NOT NULL COMMENT 'VIP 等级',
    has_app         TINYINT UNSIGNED NOT NULL COMMENT '是否安装 App，0/1',
    ai_summary            TEXT     NULL COMMENT 'AI 画像摘要（模板或远程模型生成）',
    ai_summary_generated_at DATETIME(3) NULL COMMENT 'AI 摘要生成时间',
    etl_batch_id    VARCHAR(64)    NOT NULL DEFAULT 'student_pkg_20260331' COMMENT 'ETL 批次',
    loaded_at       TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (customer_id),
    KEY idx_ods_customer_risk_vip (risk_appetite, vip_level),
    KEY idx_ods_customer_city (city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='客户原始表';

CREATE TABLE IF NOT EXISTS ods_product (
    product_id       VARCHAR(16)    NOT NULL COMMENT '产品唯一标识',
    product_name     VARCHAR(128)   NOT NULL COMMENT '产品名称',
    product_type     VARCHAR(32)    NOT NULL COMMENT '产品类型',
    risk_level       CHAR(2)        NOT NULL COMMENT '风险等级 R1-R5',
    expected_return  DECIMAL(10, 6) NOT NULL COMMENT '预期年化收益率',
    volatility       DECIMAL(10, 6) NOT NULL COMMENT '年化波动率',
    min_invest       DECIMAL(18, 2) NOT NULL COMMENT '最低投资金额（元）',
    duration_days    INT UNSIGNED   NOT NULL COMMENT '存续期（天）',
    liquidity        VARCHAR(16)    NOT NULL COMMENT '流动性',
    launch_date      DATE           NOT NULL COMMENT '成立日期',
    etl_batch_id     VARCHAR(64)    NOT NULL DEFAULT 'student_pkg_20260331' COMMENT 'ETL 批次',
    loaded_at        TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (product_id),
    KEY idx_ods_product_type_risk (product_type, risk_level),
    KEY idx_ods_product_liquidity (liquidity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='产品原始表';

CREATE TABLE IF NOT EXISTS ods_holding (
    holding_id     VARCHAR(64)    NOT NULL COMMENT '持仓记录唯一标识',
    customer_id    VARCHAR(64)    NOT NULL COMMENT '客户标识',
    product_id     VARCHAR(16)    NOT NULL COMMENT '产品标识',
    amount         DECIMAL(18, 2) NOT NULL COMMENT '持仓金额（元）',
    buy_date       DATE           NOT NULL COMMENT '购买日期',
    etl_batch_id   VARCHAR(64)    NOT NULL DEFAULT 'student_pkg_20260331' COMMENT 'ETL 批次',
    loaded_at      TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (holding_id),
    KEY idx_ods_holding_customer_date (customer_id, buy_date),
    KEY idx_ods_holding_product_date (product_id, buy_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='持仓原始表';

CREATE TABLE IF NOT EXISTS ods_campaign (
    contact_id     VARCHAR(64) NOT NULL COMMENT '触达记录唯一标识',
    customer_id    VARCHAR(64) NOT NULL COMMENT '客户标识',
    product_id     VARCHAR(16) NOT NULL COMMENT '产品标识',
    channel        VARCHAR(16) NOT NULL COMMENT '触达渠道',
    contact_date   DATE        NOT NULL COMMENT '触达日期',
    responded      TINYINT UNSIGNED NOT NULL COMMENT '是否响应，0/1',
    etl_batch_id   VARCHAR(64) NOT NULL DEFAULT 'student_pkg_20260331' COMMENT 'ETL 批次',
    loaded_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (contact_id),
    KEY idx_ods_campaign_customer_date (customer_id, contact_date),
    KEY idx_ods_campaign_product_date (product_id, contact_date),
    KEY idx_ods_campaign_channel_date (channel, contact_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='营销触达原始表';

CREATE TABLE IF NOT EXISTS ods_event (
    event_id       VARCHAR(64) NOT NULL COMMENT '行为事件唯一标识',
    customer_id    VARCHAR(64) NOT NULL COMMENT '客户标识',
    event_type     VARCHAR(32) NOT NULL COMMENT '事件类型',
    event_date     DATE        NOT NULL COMMENT '事件日期',
    etl_batch_id   VARCHAR(64) NOT NULL DEFAULT 'student_pkg_20260331' COMMENT 'ETL 批次',
    loaded_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (event_id),
    KEY idx_ods_event_customer_date (customer_id, event_date),
    KEY idx_ods_event_type_date (event_type, event_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='客户行为事件原始表';

CREATE TABLE IF NOT EXISTS dwd_dim_customer (
    customer_id     VARCHAR(64)      NOT NULL COMMENT '客户唯一标识',
    age_group       VARCHAR(16)      NOT NULL COMMENT '年龄段',
    city            VARCHAR(32)      NOT NULL COMMENT '城市',
    occupation      VARCHAR(32)      NOT NULL COMMENT '职业',
    income_level    VARCHAR(32)      NOT NULL COMMENT '收入区间',
    register_date   DATE             NOT NULL COMMENT '注册日期',
    aum             DECIMAL(18, 2)   NOT NULL COMMENT '资产管理规模（元）',
    risk_appetite   CHAR(2)          NOT NULL COMMENT '风险偏好 R1-R5',
    vip_level       VARCHAR(16)      NOT NULL COMMENT 'VIP 等级',
    has_app         TINYINT UNSIGNED NOT NULL COMMENT '是否安装 App，0/1',
    source_batch_id VARCHAR(64)      NOT NULL COMMENT '来源批次',
    processed_at    TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加工时间',
    PRIMARY KEY (customer_id),
    KEY idx_dwd_customer_risk_vip (risk_appetite, vip_level),
    KEY idx_dwd_customer_city (city),
    CONSTRAINT chk_dwd_customer_aum CHECK (aum >= 0),
    CONSTRAINT chk_dwd_customer_risk CHECK (risk_appetite IN ('R1', 'R2', 'R3', 'R4', 'R5')),
    CONSTRAINT chk_dwd_customer_has_app CHECK (has_app IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DWD 客户维表';

CREATE TABLE IF NOT EXISTS dwd_dim_product (
    product_id       VARCHAR(16)    NOT NULL COMMENT '产品唯一标识',
    product_name     VARCHAR(128)   NOT NULL COMMENT '产品名称',
    product_type     VARCHAR(32)    NOT NULL COMMENT '产品类型',
    risk_level       CHAR(2)        NOT NULL COMMENT '风险等级 R1-R5',
    expected_return  DECIMAL(10, 6) NOT NULL COMMENT '预期年化收益率',
    volatility       DECIMAL(10, 6) NOT NULL COMMENT '年化波动率',
    min_invest       DECIMAL(18, 2) NOT NULL COMMENT '最低投资金额（元）',
    duration_days    INT UNSIGNED   NOT NULL COMMENT '存续期（天）',
    liquidity        VARCHAR(16)    NOT NULL COMMENT '流动性',
    launch_date      DATE           NOT NULL COMMENT '成立日期',
    source_batch_id  VARCHAR(64)    NOT NULL COMMENT '来源批次',
    processed_at     TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加工时间',
    PRIMARY KEY (product_id),
    KEY idx_dwd_product_type_risk (product_type, risk_level),
    KEY idx_dwd_product_liquidity (liquidity),
    CONSTRAINT chk_dwd_product_risk CHECK (risk_level IN ('R1', 'R2', 'R3', 'R4', 'R5')),
    CONSTRAINT chk_dwd_product_numeric CHECK (volatility >= 0 AND min_invest >= 0),
    CONSTRAINT chk_dwd_product_liquidity CHECK (liquidity IN ('T+0', 'T+1', '封闭'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DWD 产品维表';

CREATE TABLE IF NOT EXISTS dwd_fact_holding (
    holding_id      VARCHAR(64)    NOT NULL COMMENT '持仓记录唯一标识',
    customer_id     VARCHAR(64)    NOT NULL COMMENT '客户标识',
    product_id      VARCHAR(16)    NOT NULL COMMENT '产品标识',
    amount          DECIMAL(18, 2) NOT NULL COMMENT '持仓金额（元）',
    buy_date        DATE           NOT NULL COMMENT '购买日期',
    source_batch_id VARCHAR(64)    NOT NULL COMMENT '来源批次',
    processed_at    TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加工时间',
    PRIMARY KEY (holding_id),
    KEY idx_dwd_holding_customer_date (customer_id, buy_date),
    KEY idx_dwd_holding_product_date (product_id, buy_date),
    CONSTRAINT chk_dwd_holding_amount CHECK (amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DWD 持仓事实表';

CREATE TABLE IF NOT EXISTS dwd_fact_campaign (
    contact_id      VARCHAR(64)      NOT NULL COMMENT '触达记录唯一标识',
    customer_id     VARCHAR(64)      NOT NULL COMMENT '客户标识',
    product_id      VARCHAR(16)      NOT NULL COMMENT '产品标识',
    channel         VARCHAR(16)      NOT NULL COMMENT '触达渠道',
    contact_date    DATE             NOT NULL COMMENT '触达日期',
    responded       TINYINT UNSIGNED NOT NULL COMMENT '是否响应，0/1',
    source_batch_id VARCHAR(64)      NOT NULL COMMENT '来源批次',
    processed_at    TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加工时间',
    PRIMARY KEY (contact_id),
    KEY idx_dwd_campaign_customer_date (customer_id, contact_date),
    KEY idx_dwd_campaign_product_date (product_id, contact_date),
    KEY idx_dwd_campaign_channel_date (channel, contact_date),
    CONSTRAINT chk_dwd_campaign_responded CHECK (responded IN (0, 1)),
    CONSTRAINT chk_dwd_campaign_channel CHECK (channel IN ('sms', 'call', 'app_push', 'manager'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DWD 营销触达事实表';

CREATE TABLE IF NOT EXISTS dwd_fact_event (
    event_id        VARCHAR(64) NOT NULL COMMENT '行为事件唯一标识',
    customer_id     VARCHAR(64) NOT NULL COMMENT '客户标识',
    event_type      VARCHAR(32) NOT NULL COMMENT '事件类型',
    event_date      DATE        NOT NULL COMMENT '事件日期',
    source_batch_id VARCHAR(64) NOT NULL COMMENT '来源批次',
    processed_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加工时间',
    PRIMARY KEY (event_id),
    KEY idx_dwd_event_customer_date (customer_id, event_date),
    KEY idx_dwd_event_type_date (event_type, event_date),
    CONSTRAINT chk_dwd_event_type CHECK (event_type IN ('login', 'consult', 'complaint'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DWD 客户行为事实表';

CREATE TABLE IF NOT EXISTS ref_product_correlation (
    product_id         VARCHAR(16) NOT NULL COMMENT '产品标识',
    related_product_id VARCHAR(16) NOT NULL COMMENT '关联产品标识',
    correlation        DOUBLE      NOT NULL COMMENT '相关系数',
    etl_batch_id       VARCHAR(64) NOT NULL DEFAULT 'student_pkg_20260331' COMMENT '数据批次',
    loaded_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (product_id, related_product_id),
    KEY idx_ref_correlation_related_product (related_product_id),
    CONSTRAINT chk_ref_correlation_range CHECK (correlation BETWEEN -1 AND 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='组合优化相关矩阵参考数据';

CREATE TABLE IF NOT EXISTS app_portfolio_scenario (
    scenario_id          VARCHAR(64)    NOT NULL COMMENT '场景标识',
    scenario_name        VARCHAR(128)   NOT NULL COMMENT '场景名称',
    scenario_type        VARCHAR(16)    NOT NULL COMMENT 'preset/custom',
    total_amount         DECIMAL(18, 2) NOT NULL COMMENT '投资总金额',
    risk_aversion        DECIMAL(10, 6) NOT NULL COMMENT '风险厌恶系数',
    max_single_weight    DECIMAL(10, 6) NOT NULL COMMENT '单产品最大权重',
    max_high_risk_weight DECIMAL(10, 6) NOT NULL COMMENT '高风险产品最大权重',
    min_liquid_weight    DECIMAL(10, 6) NOT NULL COMMENT '最低流动资产权重',
    min_holdings         INT UNSIGNED   NOT NULL COMMENT '最低持仓产品数',
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (scenario_id),
    KEY idx_app_scenario_type (scenario_type),
    CONSTRAINT chk_app_scenario_type CHECK (scenario_type IN ('preset', 'custom'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='组合优化场景配置';

CREATE TABLE IF NOT EXISTS app_campaign_event (
    campaign_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '触达事件唯一标识',
    strategy_id       VARCHAR(64)    NOT NULL COMMENT '关联策略（约定 {customer_id}:{rank}）',
    event_type        VARCHAR(16)    NOT NULL COMMENT '事件类型 sent/responded',
    occurred_at       DATETIME       NOT NULL COMMENT '事件发生时间',
    product_id        VARCHAR(16)    NULL COMMENT 'responded 事件归因的购买产品',
    amount            DECIMAL(18, 2) NULL COMMENT 'responded 事件归因的购买金额',
    created_at        TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '落库时间（审计）',
    PRIMARY KEY (campaign_event_id),
    KEY idx_campaign_event_strategy (strategy_id),
    KEY idx_campaign_event_type_time (event_type, occurred_at),
    CONSTRAINT chk_campaign_event_type CHECK (event_type IN ('sent', 'responded'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='营销触达执行事件（append-only 埋点）';

CREATE TABLE IF NOT EXISTS ads_marketing_response_score (
    contact_id             VARCHAR(64)    NOT NULL COMMENT '待预测触达记录标识',
    customer_id            VARCHAR(64)    NOT NULL COMMENT '客户标识',
    product_id             VARCHAR(16)    NOT NULL COMMENT '产品标识',
    channel                VARCHAR(16)    NOT NULL COMMENT '触达渠道',
    contact_date           DATE           NOT NULL COMMENT '计划触达日期',
    response_prob          DECIMAL(16, 15) NOT NULL COMMENT '预测响应概率',
    model_version          VARCHAR(64)    NOT NULL COMMENT '模型版本',
    feature_version        VARCHAR(64)    NOT NULL COMMENT '特征口径版本',
    feature_as_of_date     DATE           NOT NULL COMMENT '特征截止日期（不含当日）',
    explanation_json       JSON           NOT NULL COMMENT '局部模型贡献与关键证据',
    generated_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (contact_id),
    KEY idx_ads_response_customer_date (customer_id, contact_date),
    KEY idx_ads_response_product_channel (product_id, channel),
    CONSTRAINT chk_ads_response_prob CHECK (response_prob BETWEEN 0 AND 1),
    CONSTRAINT chk_ads_response_channel CHECK (channel IN ('sms', 'call', 'app_push', 'manager'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ADS 营销响应预测结果';
