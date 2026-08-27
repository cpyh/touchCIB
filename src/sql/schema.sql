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
    responded_strategy_id VARCHAR(64) GENERATED ALWAYS AS (
        CASE WHEN event_type = 'responded' THEN strategy_id ELSE NULL END
    ) STORED COMMENT '仅响应事件参与唯一约束，sent仍保持append-only',
    created_at        TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '落库时间（审计）',
    PRIMARY KEY (campaign_event_id),
    UNIQUE KEY uk_campaign_event_responded_strategy (responded_strategy_id),
    KEY idx_campaign_event_strategy (strategy_id),
    KEY idx_campaign_event_type_time (event_type, occurred_at),
    CONSTRAINT chk_campaign_event_type CHECK (event_type IN ('sent', 'responded'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='营销触达执行事件（append-only 埋点）';

CREATE TABLE IF NOT EXISTS app_demo_holding (
    holding_id             VARCHAR(64)    NOT NULL COMMENT '模拟持仓唯一标识',
    customer_id            VARCHAR(64)    NOT NULL COMMENT '客户标识',
    product_id             VARCHAR(16)    NOT NULL COMMENT '购买产品标识',
    amount                 DECIMAL(18, 2) NOT NULL COMMENT '模拟购买金额',
    buy_date               DATE           NOT NULL COMMENT '模拟购买日期',
    attributed_strategy_id VARCHAR(64)    NOT NULL COMMENT '归因策略（{customer_id}:{rank}）',
    created_at             TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '模拟数据落库时间',
    PRIMARY KEY (holding_id),
    UNIQUE KEY uk_demo_holding_strategy (attributed_strategy_id),
    KEY idx_demo_holding_customer_date (customer_id, buy_date),
    CONSTRAINT chk_demo_holding_amount CHECK (amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='演示专用新增持仓（不污染原始 t_holding）';

CREATE TABLE IF NOT EXISTS ads_a1_customer_product_score (
    strategy_date       DATE             NOT NULL COMMENT '策略批次日期；特征仅使用该日之前数据',
    customer_id        VARCHAR(64)      NOT NULL COMMENT '客户标识',
    product_id         VARCHAR(16)      NOT NULL COMMENT '候选产品标识',
    recommended_channel VARCHAR(16)     NOT NULL COMMENT '规则预选的可执行渠道',
    response_prob      DECIMAL(16, 15) NOT NULL COMMENT 'A1客户×产品×渠道响应概率',
    a1_rank            TINYINT UNSIGNED NOT NULL COMMENT '客户内30产品A1概率排名',
    model_version      VARCHAR(64)      NOT NULL COMMENT 'A1模型版本',
    feature_version    VARCHAR(64)      NOT NULL COMMENT '特征口径版本',
    feature_as_of_date DATE             NOT NULL COMMENT '特征截止日期（不含当日）',
    batch_id           VARCHAR(64)      NOT NULL COMMENT '幂等批次标识',
    generated_at       TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (strategy_date, customer_id, product_id),
    KEY idx_ads_a1_date_probability (strategy_date, response_prob),
    KEY idx_ads_a1_customer_rank (strategy_date, customer_id, a1_rank),
    CONSTRAINT chk_ads_a1_product_prob CHECK (response_prob BETWEEN 0 AND 1),
    CONSTRAINT chk_ads_a1_product_channel CHECK (recommended_channel IN ('sms', 'call', 'app_push', 'manager')),
    CONSTRAINT chk_ads_a1_product_rank CHECK (a1_rank BETWEEN 1 AND 30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ADS A1全量客户产品评分；业务查询不读取提交CSV';

CREATE TABLE IF NOT EXISTS ads_a2_candidate_decision (
    strategy_date       DATE             NOT NULL COMMENT '策略批次日期',
    customer_id        VARCHAR(64)      NOT NULL COMMENT '客户标识',
    product_id         VARCHAR(16)      NOT NULL COMMENT '候选产品标识',
    a1_rank            TINYINT UNSIGNED NOT NULL COMMENT '过滤前A1排名',
    response_prob      DECIMAL(16, 15) NOT NULL COMMENT 'A1响应概率',
    recommended_channel VARCHAR(16)     NOT NULL COMMENT '规则预选渠道',
    rule_passed        TINYINT(1)       NOT NULL COMMENT '是否通过A2基础硬规则',
    rule_trace_json    JSON             NOT NULL COMMENT '逐条规则判断证据',
    filter_reason      VARCHAR(512)     NULL COMMENT '被过滤原因；通过时为空',
    batch_id           VARCHAR(64)      NOT NULL COMMENT '幂等批次标识',
    generated_at       TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (strategy_date, customer_id, product_id),
    KEY idx_ads_a2_candidate_pass_rank (strategy_date, customer_id, rule_passed, response_prob),
    CONSTRAINT chk_ads_a2_candidate_passed CHECK (rule_passed IN (0, 1)),
    CONSTRAINT chk_ads_a2_candidate_prob CHECK (response_prob BETWEEN 0 AND 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ADS A2候选过滤轨迹；A1排序后应用基础业务规则';

CREATE TABLE IF NOT EXISTS ads_marketing_strategy (
    strategy_date       DATE             NOT NULL COMMENT '策略批次日期与归因窗口起点',
    customer_id        VARCHAR(64)      NOT NULL COMMENT '客户标识',
    strategy_rank      TINYINT UNSIGNED NOT NULL COMMENT '过滤后Top3顺序',
    strategy_id        VARCHAR(96)      NOT NULL COMMENT '执行标识；当前活动沿用customer_id:rank',
    product_id         VARCHAR(16)      NOT NULL COMMENT '推荐产品标识',
    recommended_channel VARCHAR(16)     NOT NULL COMMENT '推荐渠道',
    recommended_time   VARCHAR(32)      NOT NULL COMMENT '推荐联系时段',
    marketing_script   VARCHAR(300)     NOT NULL COMMENT '规则生成并校验的话术',
    a1_probability     DECIMAL(16, 15) NOT NULL COMMENT '进入A2前的A1响应概率',
    a1_rank            TINYINT UNSIGNED NOT NULL COMMENT '过滤前A1产品排名',
    rule_trace_json    JSON             NOT NULL COMMENT '产品、渠道、时段和话术规则证据',
    selection_reason   VARCHAR(512)     NOT NULL COMMENT '从A1排名到Top3的选择说明',
    model_version      VARCHAR(64)      NOT NULL COMMENT 'A1模型版本',
    rule_version       VARCHAR(64)      NOT NULL COMMENT 'A2规则版本',
    batch_id           VARCHAR(64)      NOT NULL COMMENT '幂等批次标识',
    generated_at       TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (strategy_date, customer_id, strategy_rank),
    UNIQUE KEY uk_ads_marketing_strategy_product (strategy_date, customer_id, product_id),
    KEY idx_ads_marketing_strategy_latest (customer_id, strategy_date),
    KEY idx_ads_marketing_strategy_channel (strategy_date, recommended_channel),
    CONSTRAINT chk_ads_marketing_strategy_rank CHECK (strategy_rank BETWEEN 1 AND 3),
    CONSTRAINT chk_ads_marketing_strategy_a1_rank CHECK (a1_rank BETWEEN 1 AND 30),
    CONSTRAINT chk_ads_marketing_strategy_prob CHECK (a1_probability BETWEEN 0 AND 1),
    CONSTRAINT chk_ads_marketing_strategy_channel CHECK (recommended_channel IN ('sms', 'call', 'app_push', 'manager'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ADS营销Top3批处理结果；前后端唯一策略读取来源';

CREATE TABLE IF NOT EXISTS ads_portfolio_result (
    calculation_date       DATE             NOT NULL COMMENT '组合批次日期',
    scenario_id            VARCHAR(64)      NOT NULL COMMENT '场景标识',
    total_amount           DECIMAL(18, 2)   NOT NULL COMMENT '配置总金额',
    expected_return        DECIMAL(16, 12)  NOT NULL COMMENT '组合预期收益',
    portfolio_volatility   DECIMAL(16, 12)  NOT NULL COMMENT '组合波动率',
    utility                DECIMAL(20, 12)  NOT NULL COMMENT '目标效用',
    cash_weight            DECIMAL(16, 12)  NOT NULL COMMENT '现金权重',
    holdings_count         INT UNSIGNED     NOT NULL COMMENT '持仓产品数',
    high_risk_weight       DECIMAL(16, 12)  NOT NULL COMMENT '高风险权重',
    liquid_plus_cash       DECIMAL(16, 12)  NOT NULL COMMENT '流动资产与现金权重',
    optimality_gap         DECIMAL(20, 12)  NULL COMMENT '最优性差距',
    constraints_satisfied  TINYINT(1)       NOT NULL COMMENT '硬约束是否全部通过',
    batch_id               VARCHAR(64)      NOT NULL COMMENT '幂等批次标识',
    generated_at           TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (calculation_date, scenario_id),
    KEY idx_ads_portfolio_latest (scenario_id, calculation_date),
    CONSTRAINT chk_ads_portfolio_constraints CHECK (constraints_satisfied IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ADS组合优化场景批处理汇总';

CREATE TABLE IF NOT EXISTS ads_portfolio_allocation (
    calculation_date DATE             NOT NULL COMMENT '组合批次日期',
    scenario_id      VARCHAR(64)      NOT NULL COMMENT '场景标识',
    product_id       VARCHAR(16)      NOT NULL COMMENT '产品标识',
    weight           DECIMAL(16, 12) NOT NULL COMMENT '产品权重',
    allocation_amount DECIMAL(18, 2) NOT NULL COMMENT '配置金额',
    batch_id         VARCHAR(64)      NOT NULL COMMENT '幂等批次标识',
    generated_at     TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (calculation_date, scenario_id, product_id),
    KEY idx_ads_portfolio_allocation_scenario (scenario_id, calculation_date),
    CONSTRAINT chk_ads_portfolio_weight CHECK (weight >= 0 AND weight <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ADS组合优化产品配置明细';
