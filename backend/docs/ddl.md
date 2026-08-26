# 智能财富管理运营平台 DDL（MySQL 8.0）

> 当前包含客户画像与风险评估、营销运营工作台两个模块。营销模块仅为 A1、A2 各设置一张“导入数据 + 预测结果”表。

```sql
CREATE DATABASE IF NOT EXISTS touch_cib
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE touch_cib;

-- 1. 客户表：对应 t_customer.csv，并缓存 AI 画像总结
CREATE TABLE IF NOT EXISTS t_customer (
    customer_id              VARCHAR(32)  NOT NULL COMMENT '客户唯一标识',
    age_group                VARCHAR(16)  NOT NULL COMMENT '18-24/25-34/35-44/45-54/55-64/65+',
    city                     VARCHAR(50)  NOT NULL COMMENT '所在城市',
    occupation               VARCHAR(32)  NOT NULL COMMENT '职业',
    income_level             VARCHAR(16)  NOT NULL COMMENT '收入区间',
    register_date            DATE         NOT NULL COMMENT '注册日期',
    aum                      DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '资产管理规模（元）',
    risk_appetite            CHAR(2)      NOT NULL COMMENT '风险等级 R1-R5',
    vip_level                VARCHAR(16)  NOT NULL COMMENT '普通/银卡/金卡/钻石',
    has_app                  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否安装 App',
    ai_summary               TEXT         NULL COMMENT '最近一次 AI 结构化画像 JSON',
    ai_summary_generated_at  DATETIME(3)  NULL COMMENT 'AI 总结生成时间',
    created_at               DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at               DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                                           ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (customer_id),
    INDEX idx_customer_risk_vip (risk_appetite, vip_level),
    INDEX idx_customer_city (city),
    CONSTRAINT chk_customer_aum CHECK (aum >= 0),
    CONSTRAINT chk_customer_risk CHECK (risk_appetite IN ('R1','R2','R3','R4','R5')),
    CONSTRAINT chk_customer_has_app CHECK (has_app IN (0,1))
) ENGINE=InnoDB COMMENT='客户基础信息及当前风险等级';

-- 2. 产品表：对应 t_product.csv
CREATE TABLE IF NOT EXISTS t_product (
    product_id       VARCHAR(32)  NOT NULL COMMENT '产品唯一标识',
    product_name     VARCHAR(100) NOT NULL COMMENT '产品名称',
    product_type     VARCHAR(32)  NOT NULL COMMENT '产品类型',
    risk_level       CHAR(2)      NOT NULL COMMENT '产品风险等级 R1-R5',
    expected_return  DECIMAL(10,6) NOT NULL COMMENT '预期年化收益率',
    volatility       DECIMAL(10,6) NOT NULL COMMENT '年化波动率',
    min_invest       DECIMAL(18,2) NOT NULL COMMENT '最低投资金额',
    duration_days    INT UNSIGNED NOT NULL COMMENT '存续期（天）',
    liquidity        VARCHAR(16)  NOT NULL COMMENT 'T+0/T+1/封闭',
    launch_date      DATE         NOT NULL COMMENT '成立日期',
    created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                                    ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (product_id),
    INDEX idx_product_type_risk (product_type, risk_level),
    CONSTRAINT chk_product_risk CHECK (risk_level IN ('R1','R2','R3','R4','R5')),
    CONSTRAINT chk_product_volatility CHECK (volatility >= 0),
    CONSTRAINT chk_product_min_invest CHECK (min_invest >= 0)
) ENGINE=InnoDB COMMENT='财富产品基础信息';

-- 3. 持仓表：对应 t_holding.csv，连接客户与产品
CREATE TABLE IF NOT EXISTS t_holding (
    holding_id   VARCHAR(32)  NOT NULL COMMENT '持仓记录唯一标识',
    customer_id  VARCHAR(32)  NOT NULL COMMENT '客户 ID',
    product_id   VARCHAR(32)  NOT NULL COMMENT '产品 ID',
    amount       DECIMAL(18,2) NOT NULL COMMENT '持仓金额（元）',
    buy_date     DATE         NOT NULL COMMENT '购买日期',
    created_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
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
) ENGINE=InnoDB COMMENT='客户产品持仓';

-- 4. 行为事件表：对应 t_event.csv
CREATE TABLE IF NOT EXISTS t_event (
    event_id     VARCHAR(32) NOT NULL COMMENT '事件唯一标识',
    customer_id  VARCHAR(32) NOT NULL COMMENT '客户 ID',
    event_type   VARCHAR(32) NOT NULL COMMENT 'login/consult/complaint',
    event_date   DATE        NOT NULL COMMENT '事件日期',
    created_at   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (event_id),
    INDEX idx_event_customer_date (customer_id, event_date),
    INDEX idx_event_type_date (event_type, event_date),
    CONSTRAINT fk_event_customer FOREIGN KEY (customer_id)
        REFERENCES t_customer (customer_id),
    CONSTRAINT chk_event_type CHECK (event_type IN ('login','consult','complaint'))
) ENGINE=InnoDB COMMENT='客户行为事件';

-- 5. A1 导入及响应预测表：一条记录对应一条待预测触达
CREATE TABLE IF NOT EXISTS t_a1_prediction (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_no          VARCHAR(40)  NOT NULL COMMENT '导入批次号',
    source_file_name  VARCHAR(255) NOT NULL COMMENT '原始导入文件名',
    contact_id        VARCHAR(64)  NOT NULL COMMENT '待预测触达编号',
    customer_id       VARCHAR(32)  NOT NULL COMMENT '客户 ID',
    product_id        VARCHAR(32)  NOT NULL COMMENT '本次触达产品 ID',
    channel           VARCHAR(20)  NOT NULL COMMENT 'sms/call/app_push/manager',
    contact_date      DATE         NOT NULL COMMENT '计划触达日期',
    response_prob     DECIMAL(12,10) NULL COMMENT 'A1 响应概率，预测前为空',
    status            VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                                     COMMENT 'PENDING/PROCESSING/SUCCESS/FAILED',
    error_message     VARCHAR(500) NULL COMMENT '预测失败原因',
    created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    predicted_at      DATETIME(3)  NULL COMMENT '预测完成时间',
    updated_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                                     ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_a1_batch_contact (batch_no, contact_id),
    INDEX idx_a1_batch_status (batch_no, status),
    INDEX idx_a1_batch_customer_prob (batch_no, customer_id, response_prob),
    INDEX idx_a1_customer_predicted (customer_id, predicted_at),
    CONSTRAINT fk_a1_customer FOREIGN KEY (customer_id)
        REFERENCES t_customer (customer_id),
    CONSTRAINT fk_a1_product FOREIGN KEY (product_id)
        REFERENCES t_product (product_id),
    CONSTRAINT chk_a1_channel CHECK (channel IN ('sms','call','app_push','manager')),
    CONSTRAINT chk_a1_probability CHECK (response_prob IS NULL OR response_prob BETWEEN 0 AND 1),
    CONSTRAINT chk_a1_status CHECK (status IN ('PENDING','PROCESSING','SUCCESS','FAILED'))
) ENGINE=InnoDB COMMENT='A1 待预测触达及响应概率结果';

-- 6. A2 导入及 Top 3 策略表：一条记录对应一位客户的一组 Top 3
CREATE TABLE IF NOT EXISTS t_a2_prediction (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_no          VARCHAR(40)  NOT NULL COMMENT '导入或单客生成批次号',
    source_file_name  VARCHAR(255) NULL COMMENT '批量导入文件名，单客生成为空',
    customer_id       VARCHAR(32)  NOT NULL COMMENT '客户 ID',
    strategy_date     DATE         NOT NULL COMMENT '策略日期',
    source_type       VARCHAR(16)  NOT NULL DEFAULT 'IMPORT' COMMENT 'IMPORT/MANUAL',
    top3_result       JSON         NULL COMMENT '固定包含 rank 1/2/3 的策略数组',
    status            VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                                     COMMENT 'PENDING/PROCESSING/SUCCESS/FAILED',
    error_message     VARCHAR(500) NULL COMMENT '生成失败原因',
    created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    predicted_at      DATETIME(3)  NULL COMMENT '策略生成完成时间',
    updated_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                                     ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_a2_batch_customer (batch_no, customer_id),
    INDEX idx_a2_batch_status (batch_no, status),
    INDEX idx_a2_batch_source (batch_no, source_type),
    INDEX idx_a2_customer_latest (customer_id, status, predicted_at),
    CONSTRAINT fk_a2_customer FOREIGN KEY (customer_id)
        REFERENCES t_customer (customer_id),
    CONSTRAINT chk_a2_source CHECK (source_type IN ('IMPORT','MANUAL')),
    CONSTRAINT chk_a2_status CHECK (status IN ('PENDING','PROCESSING','SUCCESS','FAILED'))
) ENGINE=InnoDB COMMENT='A2 目标客户及 Top 3 营销策略结果';
```

## CSV 导入说明

- 导入 `t_customer.csv` 时，直接保存文件中的 `risk_appetite`。
- 新建客户时，客户端不提交 `risk_appetite`，后端计算后只保存最终的 R1～R5。
- `t_product.csv`、`t_holding.csv`、`t_event.csv` 可直接映射同名业务表，时间戳字段使用数据库默认值。
- 导入 `partA_test_contacts.csv` 时生成 A1 批次号，记录写入 `t_a1_prediction`，初始状态为 `PENDING`。
- 导入 `partA_strategy_customers.csv` 时生成 A2 批次号，记录写入 `t_a2_prediction`，初始状态为 `PENDING`、`source_type='IMPORT'`。
- 单客生成 Top 3 时直接在 `t_a2_prediction` 新建 `source_type='MANUAL'` 的记录，不进入正式 A2 导出。
