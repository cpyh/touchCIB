"""Part A 特征工程：拼表 + 基础特征（第 2 步）。

设计纪律
--------
1. **train / test 共用同一个 `build_features` 函数**，避免两份代码不一致。
2. 本模块只做"拼完就有"和"当前行自算"的特征，**不涉及任何历史聚合统计**，
   因此天然没有时间穿越与目标泄漏问题（历史统计特征属第 3 步）。
3. 特征清单集中在 `FeatureSpec`，与训练脚本解耦。

特征来源
--------
- `t_customer` 按 customer_id 多对一 left join（主键唯一，行数不膨胀）
- `t_product`  按 product_id  多对一 left join（同上）
- 已核查：train / test 的客户与产品覆盖率均为 100%，join 后无缺失。

日历特征（星期/月份/是否周末）**故意不加**：
测试集 contact_date 仅 2026-04-15 单一取值，这些特征在测试集上退化为常量，
对 AUC / Lift 这类只依赖排序的指标贡献恒为 0，且置换检验显示其与随机噪声
无法区分（p 值 0.12~0.33），加入只会带来过拟合风险。
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import config


# ================================================================ 特征清单


# 原始类别（11）：无序，交给 one-hot
CATEGORICAL_RAW = [
    "channel",
    "product_id",
    "product_type",
    "risk_level",
    "liquidity",
    "age_group",
    "city",
    "occupation",
    "income_level",
    "risk_appetite",
    "vip_level",
]

# 交互类别（2）：拼成新类别再 one-hot。
# LR 是线性模型，不显式给交叉项就学不到交互效应
# （实测 channel×vip 响应率极差 0.713，manager×钻石=0.745 vs sms×普通=0.032）
CATEGORICAL_CROSS = [
    "channel_x_vip",
    "channel_x_has_app",
]

CATEGORICAL_ALL = CATEGORICAL_RAW + CATEGORICAL_CROSS

# 原始数值（7）
NUMERIC_RAW = [
    "aum",
    "has_app",
    "expected_return",
    "volatility",
    "min_invest",
    "duration_days",
]

# 有序映射（4）：这些字段本身有序，额外给出数字版本以保留大小关系
NUMERIC_ORDINAL = [
    "income_ord",
    "vip_ord",
    "cust_risk_num",
    "prod_risk_num",
]

# 时间差（1）
NUMERIC_TIMEDELTA = [
    "product_age_days",
]

# 交互数值（6）
NUMERIC_INTERACTION = [
    "risk_gap",
    "abs_risk_gap",
    "is_risk_over",
    "aum_ge_min_invest",
    "log_aum_over_min_invest",
    "sharpe",
]

NUMERIC_ALL = NUMERIC_RAW + NUMERIC_ORDINAL + NUMERIC_TIMEDELTA + NUMERIC_INTERACTION

# 高度右偏、需要 log 变换后再标准化的列（LR 对偏态敏感）
# aum: p50=121,668 而 max=7,096,874，最大值是中位数的 58 倍
LOG_SCALE_COLS = ["aum", "min_invest"]


# ================================================================ 有序映射表

INCOME_ORDER = {"10万以下": 0, "10-30万": 1, "30-50万": 2, "50万以上": 3}
VIP_ORDER = {"普通": 0, "银卡": 1, "金卡": 2, "钻石": 3}


def _risk_to_num(series: pd.Series) -> pd.Series:
    """R1..R5 -> 1..5"""
    return series.str.slice(1).astype(int)


# ================================================================ 数据加载


def load_base_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """加载 t_customer 与 t_product。"""
    customer = pd.read_csv(
        os.path.join(config.DATA_DIR, "t_customer.csv"),
        parse_dates=["register_date"],
    )
    product = pd.read_csv(
        os.path.join(config.DATA_DIR, "t_product.csv"),
        parse_dates=["launch_date"],
    )
    return customer, product


def load_train_contacts() -> pd.DataFrame:
    """训练用触达记录（含 responded 标签）。"""
    return pd.read_csv(
        os.path.join(config.DATA_DIR, "t_campaign.csv"),
        parse_dates=["contact_date"],
    )


def load_test_contacts() -> pd.DataFrame:
    """待预测触达名单（不含标签）。"""
    return pd.read_csv(config.TEST_CONTACTS_CSV, parse_dates=["contact_date"])


# ================================================================ 核心：拼表 + 造特征


def build_features(
    contacts: pd.DataFrame,
    customer: pd.DataFrame,
    product: pd.DataFrame,
) -> pd.DataFrame:
    """把触达记录拼上客户与产品信息，并派生基础特征。

    train 与 test 必须调用同一个函数，保证特征完全一致。

    Args:
        contacts: 触达记录，需含 customer_id / product_id / channel / contact_date
        customer: t_customer
        product:  t_product

    Returns:
        拼接并派生后的 DataFrame，行数与 contacts 一致。
    """
    n_before = len(contacts)

    df = contacts.merge(customer, on="customer_id", how="left").merge(
        product, on="product_id", how="left"
    )

    # 多对一 join 不应改变行数；一旦变化说明右表主键有重复
    if len(df) != n_before:
        raise ValueError(f"join 后行数由 {n_before} 变为 {len(df)}，右表主键可能重复")

    # ---------------- 有序映射
    # 这些字段本身有序（实测响应率单调：收入 0.107->0.318，VIP 0.149->0.364），
    # 给出数字版本以保留大小关系；同时 risk_gap 的计算依赖 *_risk_num。
    income_ser = pd.Series(df["income_level"])
    vip_ser = pd.Series(df["vip_level"])
    df["income_ord"] = income_ser.map(INCOME_ORDER).astype("int8")
    df["vip_ord"] = vip_ser.map(VIP_ORDER).astype("int8")
    df["cust_risk_num"] = _risk_to_num(pd.Series(df["risk_appetite"])).astype("int8")
    df["prod_risk_num"] = _risk_to_num(pd.Series(df["risk_level"])).astype("int8")

    # ---------------- 时间差
    # 产品上市天数：已核查训练集无"产品未成立即被触达"的行，故不会为负
    df["product_age_days"] = (df["contact_date"] - df["launch_date"]).dt.days.astype("int32")

    # ---------------- 交互：风险匹配度
    # 实测 gap=0 响应率 0.283，gap=±4 仅 0.03~0.05
    df["risk_gap"] = (df["cust_risk_num"] - df["prod_risk_num"]).astype("int8")
    df["abs_risk_gap"] = df["risk_gap"].abs().astype("int8")
    # 产品风险高于客户承受能力（银行不宜越级销售）
    df["is_risk_over"] = (df["prod_risk_num"] > df["cust_risk_num"]).astype("int8")

    # ---------------- 交互：资金能力
    # 实测 aum < min_invest（买不起）响应率仅 0.038
    df["aum_ge_min_invest"] = (df["aum"] >= df["min_invest"]).astype("int8")
    df["log_aum_over_min_invest"] = np.log(df["aum"] / df["min_invest"])

    # ---------------- 交互：产品性价比
    df["sharpe"] = df["expected_return"] / df["volatility"]

    # ---------------- 交互：渠道组合（拼成类别，供 one-hot）
    # 没装 App 却推 app_push：响应率 0.038 vs 0.195，模型必须能看到这个组合
    df["channel_x_vip"] = df["channel"] + "_" + df["vip_level"]
    df["channel_x_has_app"] = df["channel"] + "_app" + df["has_app"].astype(str)

    return df


def get_feature_columns() -> list[str]:
    """返回全部特征列名（类别 + 数值）。"""
    return CATEGORICAL_ALL + NUMERIC_ALL


def describe_features() -> str:
    """人类可读的特征清单摘要，供 README 与答辩使用。"""
    lines = [
        f"原始类别 ({len(CATEGORICAL_RAW)}): {', '.join(CATEGORICAL_RAW)}",
        f"交互类别 ({len(CATEGORICAL_CROSS)}): {', '.join(CATEGORICAL_CROSS)}",
        f"原始数值 ({len(NUMERIC_RAW)}): {', '.join(NUMERIC_RAW)}",
        f"有序映射 ({len(NUMERIC_ORDINAL)}): {', '.join(NUMERIC_ORDINAL)}",
        f"时间差 ({len(NUMERIC_TIMEDELTA)}): {', '.join(NUMERIC_TIMEDELTA)}",
        f"交互数值 ({len(NUMERIC_INTERACTION)}): {', '.join(NUMERIC_INTERACTION)}",
        f"合计 {len(get_feature_columns())} 个特征"
        f"（{len(CATEGORICAL_ALL)} 类别 + {len(NUMERIC_ALL)} 数值）",
    ]
    return "\n".join(lines)
