# 客户画像与风险评估模块 DDL（MySQL 8.0）

> 本模块只使用客户、产品、持仓、行为事件四张表。已有客户直接使用数据集中的 `risk_appetite`；通过新建接口创建的客户由后端计算该字段。

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
    ai_summary               TEXT         NULL COMMENT '最近一次 AI 画像总结',
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
```

## CSV 导入说明

- 导入 `t_customer.csv` 时，直接保存文件中的 `risk_appetite`。
- 新建客户时，客户端不提交 `risk_appetite`，后端计算后只保存最终的 R1～R5。
- 另外三张表可以直接映射比赛 CSV 字段，时间戳字段使用数据库默认值。
