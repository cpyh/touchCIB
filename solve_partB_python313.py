#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
智能财富管理运营平台 - Part B 投资组合配置优化
================================================

适用环境
--------
Python 3.13

核心依赖
--------
numpy
scipy

输入文件
--------
data/
├── t_product.csv
├── partB_scenarios.csv
└── partB_corr_matrix.csv

输出文件
--------
partB_allocation.csv
partB_optimality_audit.csv

方法概述
--------
1. 按题目给出的产品预期收益率、波动率和相关矩阵构造协方差矩阵：
       Sigma_ij = sigma_i * sigma_j * rho_ij

2. 对每个场景最大化：
       U(w) = r^T w - lambda * sqrt(w^T Sigma w)

3. 将最大化 U 等价改写为最小化凸函数：
       f(w) = lambda * sqrt(w^T Sigma w) - r^T w

4. 使用 SciPy SLSQP + 解析梯度进行连续凸优化；
   使用多个确定性/随机可行初值验证求解稳定性。

5. 题目的流动性约束：
       高流动产品权重 + 现金权重 >= min_liquid_weight

   现金 = 1 - sum(w)，因此可等价化简为：
       封闭产品权重之和 <= 1 - min_liquid_weight

   这样全部连续约束都可写成线性约束。

6. min_holdings 是离散计数约束。
   在本比赛实际数据中，连续最优解天然满足该约束；
   本程序仍保留一个确定性的“最低持仓修复”兜底逻辑，
   以便参数被现场修改后仍能重新求解。

7. 对最终解做独立可行性验证，并利用凸函数的一阶切平面
   构造全局效用上界，计算 optimality gap。

随机过程
--------
所有随机过程固定 random_state = 42。
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, minimize, root


# ============================================================
# 1. 全局常量
# ============================================================

RANDOM_STATE = 42

# 题目自动评分约束容差
SCORER_TOL = 1e-6

# 题目规定 weight >= 1e-6 才计入持仓数。
# 如果未来需要主动“补持仓”，不建议刚好使用 1e-6，
# 因为 CSV 四舍五入和浮点计算会带来边界风险。
HOLDING_FLOOR = 1e-5

# 将绝对值低于该值的数视作纯数值噪声并清零。
NUMERIC_ZERO = 1e-12

# 输出权重的小数位数。
# 12 位足够保留当前问题的高精度解，也远高于评分容差。
OUTPUT_DECIMALS = 12

# SLSQP 多起点数量。
# 本问题只有 30 个变量、20 个场景，6 个起点开销很小。
N_STARTS = 6


# ============================================================
# 2. 数据结构
# ============================================================

@dataclass(frozen=True)
class ProductData:
    """30 个产品的核心数值/分类信息。"""

    product_ids: list[str]
    expected_return: np.ndarray
    volatility: np.ndarray
    risk_level: np.ndarray
    liquidity: np.ndarray


@dataclass(frozen=True)
class Scenario:
    """单个投资组合优化场景。"""

    scenario_id: str
    total_amount: float
    risk_aversion: float
    max_single_weight: float
    max_high_risk_weight: float
    min_liquid_weight: float
    min_holdings: int


@dataclass
class SolveResult:
    """单场景求解结果及诊断信息。"""

    scenario_id: str
    weights: np.ndarray
    utility: float
    expected_return: float
    portfolio_volatility: float
    cash_weight: float
    holdings_count: int
    high_risk_weight: float
    liquid_plus_cash: float
    upper_bound: float
    absolute_gap: float
    relative_gap: float
    multistart_spread: float
    used_holding_repair: bool


# ============================================================
# 3. CSV 读取工具
# ============================================================

def read_dict_csv(path: Path) -> list[dict[str, str]]:
    """使用 utf-8-sig 读取 CSV，兼容带 BOM 的文件。"""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_products(data_dir: Path) -> ProductData:
    """
    读取 t_product.csv。

    自动评分 Part B 实际使用的产品字段主要包括：
    - product_id
    - expected_return
    - volatility
    - risk_level
    - liquidity

    total_amount / min_invest 不参与自动评分中的权重可行性约束。
    """
    path = data_dir / "t_product.csv"
    rows = read_dict_csv(path)

    if not rows:
        raise ValueError(f"{path} 为空。")

    product_ids = [row["product_id"] for row in rows]

    # 防止 product_id 重复。
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("t_product.csv 中 product_id 存在重复。")

    return ProductData(
        product_ids=product_ids,
        expected_return=np.asarray(
            [float(row["expected_return"]) for row in rows], dtype=float
        ),
        volatility=np.asarray(
            [float(row["volatility"]) for row in rows], dtype=float
        ),
        risk_level=np.asarray(
            [row["risk_level"] for row in rows], dtype=object
        ),
        liquidity=np.asarray(
            [row["liquidity"] for row in rows], dtype=object
        ),
    )


def load_scenarios(data_dir: Path) -> list[Scenario]:
    """读取 20 个 partB_scenarios 场景。"""
    path = data_dir / "partB_scenarios.csv"
    rows = read_dict_csv(path)

    scenarios: list[Scenario] = []
    for row in rows:
        scenarios.append(
            Scenario(
                scenario_id=row["scenario_id"],
                total_amount=float(row["total_amount"]),
                risk_aversion=float(row["lambda"]),
                max_single_weight=float(row["max_single_weight"]),
                max_high_risk_weight=float(row["max_high_risk_weight"]),
                min_liquid_weight=float(row["min_liquid_weight"]),
                min_holdings=int(row["min_holdings"]),
            )
        )

    ids = [s.scenario_id for s in scenarios]
    if len(set(ids)) != len(ids):
        raise ValueError("partB_scenarios.csv 中 scenario_id 存在重复。")

    return scenarios


def load_correlation_matrix(
    data_dir: Path,
    expected_product_ids: list[str],
) -> np.ndarray:
    """
    读取 partB_corr_matrix.csv。

    文件第一行、第一列用于 product_id 标识。
    程序严格检查相关矩阵的行列顺序与 t_product.csv 一致，
    避免“矩阵数值正确但产品顺序错位”这种高风险错误。
    """
    path = data_dir / "partB_corr_matrix.csv"

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if len(rows) < 2:
        raise ValueError("partB_corr_matrix.csv 内容不足。")

    col_ids = rows[0][1:]
    row_ids = [row[0] for row in rows[1:]]

    if col_ids != expected_product_ids:
        raise ValueError(
            "相关矩阵列顺序与 t_product.csv 的 product_id 顺序不一致。"
        )

    if row_ids != expected_product_ids:
        raise ValueError(
            "相关矩阵行顺序与 t_product.csv 的 product_id 顺序不一致。"
        )

    corr = np.asarray(
        [[float(x) for x in row[1:]] for row in rows[1:]],
        dtype=float,
    )

    n = len(expected_product_ids)
    if corr.shape != (n, n):
        raise ValueError(
            f"相关矩阵应为 {n}x{n}，实际为 {corr.shape}。"
        )

    return corr


# ============================================================
# 4. 协方差矩阵与基础数学函数
# ============================================================

def build_covariance_matrix(
    volatility: np.ndarray,
    correlation: np.ndarray,
) -> np.ndarray:
    """
    根据题目公式构造协方差矩阵：

        Sigma_ij = sigma_i * sigma_j * rho_ij

    矩阵形式：

        Sigma = diag(volatility) @ Corr @ diag(volatility)
    """
    d = np.diag(volatility)
    sigma = d @ correlation @ d

    # 数值稳健性：强制做一次对称化。
    sigma = 0.5 * (sigma + sigma.T)

    return sigma


def check_covariance_matrix(sigma: np.ndarray) -> float:
    """
    检查协方差矩阵是否至少半正定。

    返回最小特征值。
    理论上协方差矩阵应为 PSD；如果显著出现负特征值，
    则说明相关矩阵或输入数据存在问题。
    """
    eigvals = np.linalg.eigvalsh(sigma)
    min_eig = float(eigvals.min())

    if min_eig < -1e-10:
        raise ValueError(
            "协方差矩阵不是半正定矩阵："
            f"最小特征值 = {min_eig:.6e}"
        )

    return min_eig


def portfolio_statistics(
    weights: np.ndarray,
    expected_return: np.ndarray,
    sigma: np.ndarray,
    risk_aversion: float,
) -> tuple[float, float, float]:
    """
    计算组合：
    - 预期收益
    - 年化组合波动率
    - 效用 U
    """
    ret = float(expected_return @ weights)

    variance = float(weights @ sigma @ weights)
    variance = max(variance, 0.0)
    vol = math.sqrt(variance)

    utility = ret - risk_aversion * vol

    return ret, vol, utility


def convex_objective_and_gradient(
    weights: np.ndarray,
    expected_return: np.ndarray,
    sigma: np.ndarray,
    risk_aversion: float,
) -> tuple[float, np.ndarray]:
    """
    将最大化 U 改写为最小化：

        f(w) = lambda * sqrt(w^T Sigma w) - r^T w

    解析梯度：

        grad f(w)
        = lambda * Sigma w / sqrt(w^T Sigma w) - r

    使用解析梯度可减少数值差分误差，提高 SLSQP 收敛精度。
    """
    sigma_w = sigma @ weights
    variance = float(weights @ sigma_w)

    # 正常最优解不会处于全零点，但为了防止除零，
    # 在数值层面设置极小正数。
    vol = math.sqrt(max(variance, 1e-30))

    f = risk_aversion * vol - float(expected_return @ weights)

    grad = (
        risk_aversion * sigma_w / vol
        - expected_return
    )

    return f, grad


# ============================================================
# 5. 约束建模
# ============================================================

def build_masks(products: ProductData) -> tuple[np.ndarray, np.ndarray]:
    """
    返回：
    - high_risk_mask: R4/R5
    - non_liquid_mask: 封闭产品

    题目定义高流动性为 T+0 / T+1，
    因此非高流动产品就是“封闭”产品。
    """
    high_risk_mask = np.isin(products.risk_level, ["R4", "R5"])
    non_liquid_mask = products.liquidity == "封闭"

    return high_risk_mask, non_liquid_mask


def build_linear_constraint(
    scenario: Scenario,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    n_products: int,
) -> LinearConstraint:
    """
    将主要连续约束统一写成 A w <= b。

    约束 1：
        sum(w) <= 1

    约束 3：
        sum_{R4/R5}(w) <= max_high_risk_weight

    约束 4：
        高流动性产品 + 现金 >= min_liquid_weight

    又因为：
        cash = 1 - sum(all products)

    所以：
        liquid + cash >= L
        liquid + 1 - liquid - nonliquid >= L
        1 - nonliquid >= L
        nonliquid <= 1 - L

    因此流动性约束可直接转化成：
        sum_{封闭产品}(w) <= 1 - min_liquid_weight
    """
    A = np.vstack(
        [
            np.ones(n_products, dtype=float),
            high_risk_mask.astype(float),
            non_liquid_mask.astype(float),
        ]
    )

    upper = np.asarray(
        [
            1.0,
            scenario.max_high_risk_weight,
            1.0 - scenario.min_liquid_weight,
        ],
        dtype=float,
    )

    lower = np.full(3, -np.inf, dtype=float)

    return LinearConstraint(A, lower, upper)


def build_bounds(
    scenario: Scenario,
    n_products: int,
    lower_bounds: np.ndarray | None = None,
) -> Bounds:
    """
    构造单产品上下界。

    默认：
        0 <= w_i <= max_single_weight

    当执行 min_holdings 修复时，可以给部分产品设置
    HOLDING_FLOOR 作为下界。
    """
    if lower_bounds is None:
        lb = np.zeros(n_products, dtype=float)
    else:
        lb = np.asarray(lower_bounds, dtype=float)

    ub = np.full(
        n_products,
        scenario.max_single_weight,
        dtype=float,
    )

    if np.any(lb > ub):
        raise ValueError("某些产品下界超过 max_single_weight。")

    return Bounds(lb, ub)


# ============================================================
# 6. 初始点生成
# ============================================================

def deterministic_feasible_start(
    scenario: Scenario,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    n_products: int,
) -> np.ndarray:
    """
    构造一个保守、确定性的可行初始点。

    这里只需要给 SLSQP 一个合理起点，不要求它本身很优。
    """
    base = min(0.005, scenario.max_single_weight / 10.0)
    w = np.full(n_products, base, dtype=float)

    # 给总资金约束留 20% 余量。
    if w.sum() > 0.80:
        w *= 0.80 / w.sum()

    # 给高风险约束留 20% 余量。
    high_sum = float(w[high_risk_mask].sum())
    high_target = 0.80 * scenario.max_high_risk_weight
    if high_sum > high_target and high_sum > 0:
        w[high_risk_mask] *= high_target / high_sum

    # 给封闭产品约束留 20% 余量。
    nonliq_sum = float(w[non_liquid_mask].sum())
    nonliq_target = 0.80 * (1.0 - scenario.min_liquid_weight)
    if nonliq_sum > nonliq_target and nonliq_sum > 0:
        w[non_liquid_mask] *= nonliq_target / nonliq_sum

    return w


def random_feasible_start(
    scenario: Scenario,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    n_products: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    构造随机但较保守的可行初始点。

    随机数生成器由 RANDOM_STATE=42 初始化，
    因此结果可复现。
    """
    x = rng.random(n_products)
    x /= x.sum()

    # 初始总仓位控制在约 70% 左右。
    w = 0.70 * x

    # 保证不超过单产品上限。
    w = np.minimum(
        w,
        0.90 * scenario.max_single_weight,
    )

    # 再处理总权重。
    if w.sum() > 0.85:
        w *= 0.85 / w.sum()

    # 高风险仓位缩放。
    high_sum = float(w[high_risk_mask].sum())
    high_target = 0.85 * scenario.max_high_risk_weight
    if high_sum > high_target and high_sum > 0:
        w[high_risk_mask] *= high_target / high_sum

    # 封闭产品仓位缩放。
    nonliq_sum = float(w[non_liquid_mask].sum())
    nonliq_target = 0.85 * (1.0 - scenario.min_liquid_weight)
    if nonliq_sum > nonliq_target and nonliq_sum > 0:
        w[non_liquid_mask] *= nonliq_target / nonliq_sum

    return w


# ============================================================
# 7. 连续凸问题求解
# ============================================================

def solve_with_slsqp(
    scenario: Scenario,
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    rng: np.random.Generator,
    lower_bounds: np.ndarray | None = None,
    n_starts: int = N_STARTS,
) -> tuple[np.ndarray, list[float]]:
    """
    使用 SLSQP + 多起点求解单场景。

    虽然 SLSQP 本身是一般非线性优化器，但本题连续部分是凸问题：
    - 最小化的是凸函数
    - 约束为线性约束 + box bounds

    因此只要数值求解收敛正常，所得稳定解就是连续问题的全局最优解。

    返回：
    - 最佳权重
    - 每个成功起点的效用值，用于检查求解稳定性
    """
    n = len(products.product_ids)

    bounds = build_bounds(
        scenario=scenario,
        n_products=n,
        lower_bounds=lower_bounds,
    )

    linear_constraint = build_linear_constraint(
        scenario=scenario,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        n_products=n,
    )

    starts: list[np.ndarray] = [
        deterministic_feasible_start(
            scenario,
            high_risk_mask,
            non_liquid_mask,
            n,
        )
    ]

    while len(starts) < n_starts:
        starts.append(
            random_feasible_start(
                scenario,
                high_risk_mask,
                non_liquid_mask,
                n,
                rng,
            )
        )

    # 如果某些产品被设置 HOLDING_FLOOR，
    # 需要把初始点至少提升到这些下界。
    if lower_bounds is not None:
        lb = np.asarray(lower_bounds, dtype=float)
        starts = [np.maximum(x, lb) for x in starts]

    best_w: np.ndarray | None = None
    best_u = -np.inf
    utilities: list[float] = []

    for x0 in starts:
        result = minimize(
            fun=lambda w: convex_objective_and_gradient(
                w,
                products.expected_return,
                sigma,
                scenario.risk_aversion,
            )[0],
            x0=x0,
            jac=lambda w: convex_objective_and_gradient(
                w,
                products.expected_return,
                sigma,
                scenario.risk_aversion,
            )[1],
            method="SLSQP",
            bounds=bounds,
            constraints=[linear_constraint],
            options={
                "ftol": 1e-12,
                "maxiter": 3000,
                "disp": False,
            },
        )

        if not result.success:
            # 单个起点失败不终止程序，继续尝试其余起点。
            continue

        w = np.asarray(result.x, dtype=float)

        _, _, utility = portfolio_statistics(
            w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        utilities.append(utility)

        if utility > best_u:
            best_u = utility
            best_w = w.copy()

    if best_w is None:
        raise RuntimeError(
            f"{scenario.scenario_id}: 所有 SLSQP 起点均求解失败。"
        )

    return best_w, utilities


# ============================================================
# 8. min_holdings 兜底修复
# ============================================================

def choose_extra_holdings(
    weights: np.ndarray,
    scenario: Scenario,
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    n_needed: int,
) -> list[int]:
    """
    如果连续最优解没有满足 min_holdings，则选择额外产品。

    本函数仅作为现场修改参数后的兜底。
    当前官方数据实际求出的连续最优解天然满足 min_holdings。

    选择原则：
    - 优先选择当前权重为 0 / 很小的产品
    - 用简单的独立风险调整收益近似评分：
          expected_return - lambda * volatility
    - 对会增加高风险压力、封闭资产压力的产品给予轻微惩罚

    随后真正的权重仍会交给 SLSQP 重新优化，
    这里并不直接决定最终权重。
    """
    current_support = weights >= SCORER_TOL

    standalone_score = (
        products.expected_return
        - scenario.risk_aversion * products.volatility
    )

    # 轻微惩罚受约束类别。
    score = standalone_score.copy()
    score[high_risk_mask] -= 1e-3
    score[non_liquid_mask] -= 5e-4

    candidates = np.where(~current_support)[0]

    order = candidates[np.argsort(score[candidates])[::-1]]

    return order[:n_needed].tolist()


def repair_min_holdings_if_needed(
    weights: np.ndarray,
    scenario: Scenario,
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, bool, list[float]]:
    """
    检查最低持仓数。

    若已满足：
        直接返回。

    若不足：
        1. 选出若干补充产品；
        2. 对“原支持集 + 补充产品”设置 HOLDING_FLOOR；
        3. 再次调用 SLSQP 优化其他权重。

    注意：
    这是稳健兜底，并不替代 MISOCP/组合搜索。
    对本题当前真实数据，不会触发该步骤。
    """
    count = int(np.sum(weights >= SCORER_TOL))

    if count >= scenario.min_holdings:
        return weights, False, []

    n_needed = scenario.min_holdings - count

    extra = choose_extra_holdings(
        weights=weights,
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        n_needed=n_needed,
    )

    support = weights >= SCORER_TOL
    support[extra] = True

    lower_bounds = np.zeros_like(weights)
    lower_bounds[support] = HOLDING_FLOOR

    repaired_w, utilities = solve_with_slsqp(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        rng=rng,
        lower_bounds=lower_bounds,
        n_starts=N_STARTS,
    )

    return repaired_w, True, utilities


# ============================================================
# 9. 主动集 KKT 数值精修
# ============================================================

def refine_with_active_set_kkt(
    scenario: Scenario,
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """
    在 SLSQP 已经给出稳定解的基础上，尝试利用主动集 KKT 方程精修。

    为什么做这一步：
    ----------------
    SLSQP 已经非常接近最优，但通常停在约 1e-8 ~ 1e-12 的数值精度。
    如果能够正确识别哪些约束是 active 的，可以直接求解 KKT
    一阶条件，使最优性残差进一步接近机器精度。

    本函数是“可选精修”：
    - 若 root 求解失败；
    - 或精修后违反任何题目约束；
    则调用方应继续保留原 SLSQP 解。

    当前数据中常见 active 约束：
    - 总产品权重 sum(w)=1
    - 某些场景高风险权重达到上限
    - 少量产品达到 max_single_weight
    """
    w0 = weights.copy()
    n = len(w0)

    # 判断产品是否处于正权重支持集。
    support = w0 > SCORER_TOL

    # 判断哪些正权重产品碰到单产品上限。
    upper_active = (
        support
        & (
            np.abs(w0 - scenario.max_single_weight)
            < 1e-5
        )
    )

    # 剩余为“自由正权重变量”。
    free = support & ~upper_active
    free_idx = np.where(free)[0]

    if len(free_idx) == 0:
        return w0

    # 判断高风险约束是否 active。
    high_active = (
        abs(
            float(w0[high_risk_mask].sum())
            - scenario.max_high_risk_weight
        )
        < 1e-5
    )

    # 当前题目实际解中流动性约束不是主要 active 约束，
    # 为避免把非常松的约束错误加入主动集，这里不强制把它写入 KKT。
    # 如果未来题目参数发生较大变化，可进一步扩展。

    _, grad0 = convex_objective_and_gradient(
        w0,
        products.expected_return,
        sigma,
        scenario.risk_aversion,
    )

    # KKT 对自由变量的一阶条件：
    #
    # grad_i f + mu_sum + mu_high * I(i in high risk) = 0
    #
    # 先用最小二乘估计乘子作为 root 的初始值。
    columns = [np.ones(len(free_idx))]

    if high_active:
        columns.append(
            high_risk_mask[free_idx].astype(float)
        )

    multiplier_matrix = np.vstack(columns).T

    multiplier_init = np.linalg.lstsq(
        multiplier_matrix,
        -grad0[free_idx],
        rcond=None,
    )[0]

    x0 = np.r_[
        w0[free_idx],
        multiplier_init,
    ]

    m = len(free_idx)

    def equations(x: np.ndarray) -> np.ndarray:
        w = np.zeros(n, dtype=float)

        # 已识别为上限 active 的产品直接固定在上限。
        w[upper_active] = scenario.max_single_weight

        # 自由正权重变量由 root 求。
        w[free_idx] = x[:m]

        _, grad = convex_objective_and_gradient(
            w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        mu_sum = x[m]

        if high_active:
            mu_high = x[m + 1]
        else:
            mu_high = 0.0

        eq = list(
            grad[free_idx]
            + mu_sum
            + mu_high
            * high_risk_mask[free_idx].astype(float)
        )

        # 总资金约束在当前实际最优解中为 active：
        # sum(w)=1
        eq.append(float(w.sum()) - 1.0)

        if high_active:
            eq.append(
                float(w[high_risk_mask].sum())
                - scenario.max_high_risk_weight
            )

        return np.asarray(eq, dtype=float)

    solution = root(
        equations,
        x0,
        method="lm",
        options={
            "ftol": 1e-14,
            "xtol": 1e-14,
            "gtol": 1e-14,
            "maxiter": 5000,
        },
    )

    if not solution.success:
        return w0

    refined = np.zeros(n, dtype=float)
    refined[upper_active] = scenario.max_single_weight
    refined[free_idx] = solution.x[:m]

    refined[np.abs(refined) < NUMERIC_ZERO] = 0.0

    # 精修后若出现明显负权重，则不采用。
    if np.any(refined < -SCORER_TOL):
        return w0

    refined[refined < 0] = 0.0

    return refined


# ============================================================
# 10. 独立评分口径约束检查
# ============================================================

def validate_solution(
    scenario: Scenario,
    weights: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    tol: float = SCORER_TOL,
) -> dict[str, bool]:
    """
    完全独立于求解器，按题目评分口径重新检查全部硬约束。

    原则：
        求解器说“success”不等于评分器一定判可行。
        最终必须用自己的 validator 再算一遍。
    """
    sum_weight = float(weights.sum())
    cash_weight = 1.0 - sum_weight

    high_risk_weight = float(
        weights[high_risk_mask].sum()
    )

    liquid_product_weight = float(
        weights[~non_liquid_mask].sum()
    )

    liquid_plus_cash = (
        liquid_product_weight + cash_weight
    )

    holdings_count = int(
        np.sum(weights >= SCORER_TOL)
    )

    checks = {
        # 1. 产品权重和 <= 1
        "sum_weight": sum_weight <= 1.0 + tol,

        # 2. w_i >= 0
        "nonnegative": bool(
            np.all(weights >= -tol)
        ),

        # 2. w_i <= max_single_weight
        "max_single": float(weights.max()) <= (
            scenario.max_single_weight + tol
        ),

        # 3. R4/R5 总权重上限
        "high_risk": high_risk_weight <= (
            scenario.max_high_risk_weight + tol
        ),

        # 4. 高流动产品 + 现金 >= 最低流动性
        "liquidity": liquid_plus_cash >= (
            scenario.min_liquid_weight - tol
        ),

        # 5. 持仓数
        "min_holdings": holdings_count >= (
            scenario.min_holdings
        ),
    }

    return checks


# ============================================================
# 11. 凸优化全局上界 / Optimality Gap 证书
# ============================================================

def compute_tangent_global_upper_bound(
    scenario: Scenario,
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    weights: np.ndarray,
) -> float:
    """
    利用凸函数一阶切平面，构造效用 U* 的全局上界。

    令：

        f(w) = lambda * sigma(w) - r^T w

    f 是凸函数，因此对任意 y：

        f(y) >= f(w) + grad f(w)^T (y - w)

    把右侧在“放松后的连续可行域”上最小化：

        lower_f =
            min_y [f(w) + grad f(w)^T (y-w)]

    得到：
        lower_f <= f*

    又因为：
        U* = -f*

    所以：
        U* <= -lower_f

    即：
        upper_U = -lower_f

    如果：
        upper_U - current_U

    已经非常小，就说明当前可行解距离全局最优的
    最坏差距也非常小。

    注意：
    ----------
    这里使用的是去掉 min_holdings 后的连续放松可行域。
    如果当前连续最优解本身已经满足 min_holdings，
    那么这个连续最优解也就是原题完整问题的全局最优解。
    """
    n = len(products.product_ids)

    f_value, grad = convex_objective_and_gradient(
        weights,
        products.expected_return,
        sigma,
        scenario.risk_aversion,
    )

    A = np.vstack(
        [
            np.ones(n),
            high_risk_mask.astype(float),
            non_liquid_mask.astype(float),
        ]
    )

    b = np.asarray(
        [
            1.0,
            scenario.max_high_risk_weight,
            1.0 - scenario.min_liquid_weight,
        ],
        dtype=float,
    )

    # 线性规划：
    # min grad^T y
    #
    # subject to 放松问题中的所有线性约束。
    lp = linprog(
        c=grad,
        A_ub=A,
        b_ub=b,
        bounds=[
            (0.0, scenario.max_single_weight)
            for _ in range(n)
        ],
        method="highs",
    )

    if not lp.success:
        raise RuntimeError(
            f"{scenario.scenario_id}: "
            "全局上界证书线性规划求解失败。"
        )

    lower_bound_f = (
        f_value
        - float(grad @ weights)
        + float(lp.fun)
    )

    upper_bound_u = -lower_bound_f

    return upper_bound_u


# ============================================================
# 12. 单场景完整求解流程
# ============================================================

def solve_one_scenario(
    scenario: Scenario,
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    rng: np.random.Generator,
) -> SolveResult:
    """
    单场景完整流程：

    1. 连续凸问题 SLSQP 多起点求解；
    2. 必要时 min_holdings 修复；
    3. 尝试主动集 KKT 精修；
    4. 独立约束验证；
    5. 计算组合指标；
    6. 构造全局上界；
    7. 输出 optimality gap。
    """
    # ---------- Step 1: 连续凸问题 ----------
    w, utilities = solve_with_slsqp(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        rng=rng,
    )

    all_utilities = list(utilities)

    # ---------- Step 2: min_holdings ----------
    w, used_repair, repair_utilities = (
        repair_min_holdings_if_needed(
            weights=w,
            scenario=scenario,
            products=products,
            sigma=sigma,
            high_risk_mask=high_risk_mask,
            non_liquid_mask=non_liquid_mask,
            rng=rng,
        )
    )

    all_utilities.extend(repair_utilities)

    # ---------- Step 3: KKT 精修 ----------
    refined = refine_with_active_set_kkt(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        weights=w,
    )

    # 精修后只有在满足全部题目约束、且效用不下降时才采用。
    original_stats = portfolio_statistics(
        w,
        products.expected_return,
        sigma,
        scenario.risk_aversion,
    )

    refined_checks = validate_solution(
        scenario,
        refined,
        high_risk_mask,
        non_liquid_mask,
    )

    if all(refined_checks.values()):
        refined_stats = portfolio_statistics(
            refined,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        if refined_stats[2] >= original_stats[2] - 1e-12:
            w = refined

    # ---------- Step 4: 数值清理 ----------
    w[np.abs(w) < NUMERIC_ZERO] = 0.0
    w[w < 0] = 0.0

    # ---------- Step 5: 独立评分校验 ----------
    checks = validate_solution(
        scenario,
        w,
        high_risk_mask,
        non_liquid_mask,
    )

    if not all(checks.values()):
        failed = [
            key
            for key, passed in checks.items()
            if not passed
        ]

        raise RuntimeError(
            f"{scenario.scenario_id}: "
            f"最终解违反约束：{failed}"
        )

    # ---------- Step 6: 指标 ----------
    ret, vol, utility = portfolio_statistics(
        w,
        products.expected_return,
        sigma,
        scenario.risk_aversion,
    )

    sum_weight = float(w.sum())
    cash_weight = 1.0 - sum_weight

    high_risk_weight = float(
        w[high_risk_mask].sum()
    )

    liquid_plus_cash = float(
        w[~non_liquid_mask].sum()
        + cash_weight
    )

    holdings_count = int(
        np.sum(w >= SCORER_TOL)
    )

    # ---------- Step 7: 全局上界 ----------
    upper_bound = compute_tangent_global_upper_bound(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        weights=w,
    )

    # 理论上 upper_bound >= utility。
    # 因浮点误差可能出现 -1e-16 一类微小负差，因此做 max(0, ...).
    absolute_gap = max(
        0.0,
        upper_bound - utility,
    )

    relative_gap = (
        absolute_gap
        / max(abs(upper_bound), 1e-15)
    )

    if all_utilities:
        multistart_spread = (
            max(all_utilities)
            - min(all_utilities)
        )
    else:
        multistart_spread = 0.0

    return SolveResult(
        scenario_id=scenario.scenario_id,
        weights=w,
        utility=utility,
        expected_return=ret,
        portfolio_volatility=vol,
        cash_weight=cash_weight,
        holdings_count=holdings_count,
        high_risk_weight=high_risk_weight,
        liquid_plus_cash=liquid_plus_cash,
        upper_bound=upper_bound,
        absolute_gap=absolute_gap,
        relative_gap=relative_gap,
        multistart_spread=multistart_spread,
        used_holding_repair=used_repair,
    )


# ============================================================
# 13. 提交文件写出
# ============================================================

def write_allocation_csv(
    output_path: Path,
    scenarios: list[Scenario],
    products: ProductData,
    result_map: dict[str, SolveResult],
) -> None:
    """
    写出官方要求的 partB_allocation.csv。

    列必须严格为：
        scenario_id, product_id, weight

    只输出 weight > 0 的产品行。
    """
    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.writer(f)

        writer.writerow(
            [
                "scenario_id",
                "product_id",
                "weight",
            ]
        )

        for scenario in scenarios:
            result = result_map[scenario.scenario_id]

            # 输出前进行固定小数精度处理。
            weights = np.round(
                result.weights,
                OUTPUT_DECIMALS,
            )

            for product_id, weight in zip(
                products.product_ids,
                weights,
            ):
                if weight > 0:
                    writer.writerow(
                        [
                            scenario.scenario_id,
                            product_id,
                            f"{weight:.{OUTPUT_DECIMALS}f}",
                        ]
                    )


def write_audit_csv(
    output_path: Path,
    scenarios: list[Scenario],
    result_map: dict[str, SolveResult],
) -> None:
    """
    写出诊断/答辩使用的 partB_optimality_audit.csv。

    该文件不是官方必须提交文件，
    但强烈建议在项目源码中保留。
    """
    scenario_map = {
        s.scenario_id: s
        for s in scenarios
    }

    fields = [
        "scenario_id",
        "lambda",
        "utility",
        "global_upper_bound",
        "absolute_gap_bound",
        "relative_gap_bound",
        "expected_return",
        "portfolio_volatility",
        "product_weight_sum",
        "cash_weight",
        "holdings_count",
        "required_min_holdings",
        "high_risk_weight",
        "high_risk_cap",
        "liquid_plus_cash",
        "liquid_floor",
        "max_product_weight",
        "single_product_cap",
        "multistart_utility_spread",
        "used_holding_repair",
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for scenario_id, result in result_map.items():
            scenario = scenario_map[scenario_id]

            writer.writerow(
                {
                    "scenario_id":
                        scenario_id,

                    "lambda":
                        f"{scenario.risk_aversion:.12f}",

                    "utility":
                        f"{result.utility:.15f}",

                    "global_upper_bound":
                        f"{result.upper_bound:.15f}",

                    "absolute_gap_bound":
                        f"{result.absolute_gap:.3e}",

                    "relative_gap_bound":
                        f"{result.relative_gap:.3e}",

                    "expected_return":
                        f"{result.expected_return:.12f}",

                    "portfolio_volatility":
                        f"{result.portfolio_volatility:.12f}",

                    "product_weight_sum":
                        f"{result.weights.sum():.12f}",

                    "cash_weight":
                        f"{result.cash_weight:.12f}",

                    "holdings_count":
                        result.holdings_count,

                    "required_min_holdings":
                        scenario.min_holdings,

                    "high_risk_weight":
                        f"{result.high_risk_weight:.12f}",

                    "high_risk_cap":
                        f"{scenario.max_high_risk_weight:.12f}",

                    "liquid_plus_cash":
                        f"{result.liquid_plus_cash:.12f}",

                    "liquid_floor":
                        f"{scenario.min_liquid_weight:.12f}",

                    "max_product_weight":
                        f"{result.weights.max():.12f}",

                    "single_product_cap":
                        f"{scenario.max_single_weight:.12f}",

                    "multistart_utility_spread":
                        f"{result.multistart_spread:.3e}",

                    "used_holding_repair":
                        result.used_holding_repair,
                }
            )


# ============================================================
# 14. 对落盘后的提交 CSV 再做一次最终检查
# ============================================================

def verify_written_allocation(
    allocation_path: Path,
    scenarios: list[Scenario],
    products: ProductData,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
) -> float:
    """
    重新从刚刚生成的 partB_allocation.csv 读取权重，
    按官方口径做最终独立检查。

    这一步非常重要：
    内存中的高精度解可行，不代表经过 CSV 四舍五入后一定仍可行。
    因此必须验证“真正上传的文件”。

    返回：
        落盘 CSV 的 total_U
    """
    rows = read_dict_csv(allocation_path)

    scenario_ids = {
        s.scenario_id
        for s in scenarios
    }

    product_to_index = {
        pid: i
        for i, pid in enumerate(products.product_ids)
    }

    # 初始化每个场景的 30 维零向量。
    weights_map = {
        s.scenario_id:
            np.zeros(len(products.product_ids), dtype=float)
        for s in scenarios
    }

    seen_pairs: set[tuple[str, str]] = set()

    for row in rows:
        scenario_id = row["scenario_id"]
        product_id = row["product_id"]

        if scenario_id not in scenario_ids:
            raise ValueError(
                f"提交文件出现未知 scenario_id: {scenario_id}"
            )

        if product_id not in product_to_index:
            raise ValueError(
                f"提交文件出现未知 product_id: {product_id}"
            )

        pair = (scenario_id, product_id)

        if pair in seen_pairs:
            raise ValueError(
                f"提交文件存在重复 scenario_id + product_id: {pair}"
            )

        seen_pairs.add(pair)

        try:
            weight = float(row["weight"])
        except Exception as exc:
            raise ValueError(
                f"非法 weight: {row}"
            ) from exc

        if not np.isfinite(weight):
            raise ValueError(
                f"weight 为 NaN 或 Inf: {row}"
            )

        if weight < 0:
            raise ValueError(
                f"weight < 0: {row}"
            )

        weights_map[scenario_id][
            product_to_index[product_id]
        ] = weight

    total_utility = 0.0

    for scenario in scenarios:
        w = weights_map[scenario.scenario_id]

        checks = validate_solution(
            scenario,
            w,
            high_risk_mask,
            non_liquid_mask,
        )

        if not all(checks.values()):
            failed = [
                k
                for k, v in checks.items()
                if not v
            ]

            raise RuntimeError(
                f"{scenario.scenario_id}: "
                f"落盘 CSV 校验失败：{failed}"
            )

        _, _, utility = portfolio_statistics(
            w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        total_utility += utility

    return total_utility


# ============================================================
# 15. 主程序
# ============================================================

def run(
    data_dir: Path,
    allocation_output: Path,
    audit_output: Path,
) -> None:
    """完整 Part B 求解入口。"""

    # ---------- 读取输入 ----------
    products = load_products(data_dir)
    scenarios = load_scenarios(data_dir)

    corr = load_correlation_matrix(
        data_dir,
        products.product_ids,
    )

    sigma = build_covariance_matrix(
        products.volatility,
        corr,
    )

    min_eigenvalue = check_covariance_matrix(
        sigma
    )

    high_risk_mask, non_liquid_mask = (
        build_masks(products)
    )

    # ---------- 初始化随机数生成器 ----------
    rng = np.random.default_rng(
        RANDOM_STATE
    )

    # ---------- 逐场景求解 ----------
    result_map: dict[str, SolveResult] = {}

    print("=" * 78)
    print("Part B 投资组合配置优化")
    print("=" * 78)
    print(
        f"产品数              : "
        f"{len(products.product_ids)}"
    )
    print(
        f"场景数              : "
        f"{len(scenarios)}"
    )
    print(
        f"协方差矩阵最小特征值: "
        f"{min_eigenvalue:.6e}"
    )
    print(
        f"random_state        : "
        f"{RANDOM_STATE}"
    )
    print("-" * 78)

    for scenario in scenarios:
        result = solve_one_scenario(
            scenario=scenario,
            products=products,
            sigma=sigma,
            high_risk_mask=high_risk_mask,
            non_liquid_mask=non_liquid_mask,
            rng=rng,
        )

        result_map[scenario.scenario_id] = result

        print(
            f"{scenario.scenario_id:>8s} | "
            f"lambda={scenario.risk_aversion:>5.2f} | "
            f"U={result.utility:.12f} | "
            f"upper={result.upper_bound:.12f} | "
            f"gap={result.absolute_gap:.2e} | "
            f"holdings={result.holdings_count:>2d} | "
            f"repair={result.used_holding_repair}"
        )

    # ---------- 写出文件 ----------
    allocation_output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit_output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_allocation_csv(
        allocation_output,
        scenarios,
        products,
        result_map,
    )

    write_audit_csv(
        audit_output,
        scenarios,
        result_map,
    )

    # ---------- 对真正落盘文件再验一次 ----------
    rounded_total_u = verify_written_allocation(
        allocation_output,
        scenarios,
        products,
        sigma,
        high_risk_mask,
        non_liquid_mask,
    )

    # ---------- 汇总 ----------
    in_memory_total_u = sum(
        result.utility
        for result in result_map.values()
    )

    total_upper = sum(
        result.upper_bound
        for result in result_map.values()
    )

    total_gap = max(
        0.0,
        total_upper - in_memory_total_u,
    )

    max_relative_gap = max(
        result.relative_gap
        for result in result_map.values()
    )

    min_actual_holdings = min(
        result.holdings_count
        for result in result_map.values()
    )

    repair_count = sum(
        result.used_holding_repair
        for result in result_map.values()
    )

    print("-" * 78)
    print(
        f"内存高精度 total_U    = "
        f"{in_memory_total_u:.15f}"
    )
    print(
        f"落盘 CSV total_U      = "
        f"{rounded_total_u:.15f}"
    )
    print(
        f"全局上界之和          = "
        f"{total_upper:.15f}"
    )
    print(
        f"总 optimality gap     = "
        f"{total_gap:.3e}"
    )
    print(
        f"最大单场景相对 gap    = "
        f"{max_relative_gap:.3e}"
    )
    print(
        f"最少实际持仓数        = "
        f"{min_actual_holdings}"
    )
    print(
        f"触发持仓修复场景数    = "
        f"{repair_count}"
    )
    print(
        f"提交文件              = "
        f"{allocation_output}"
    )
    print(
        f"诊断文件              = "
        f"{audit_output}"
    )
    print("=" * 78)
    print("全部场景求解完成，落盘提交文件已通过独立硬约束校验。")


# ============================================================
# 16. 命令行入口
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "智能财富管理运营平台 Part B "
            "投资组合配置优化求解器"
        )
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help=(
            "包含 t_product.csv、"
            "partB_scenarios.csv、"
            "partB_corr_matrix.csv 的目录"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "partB_allocation.csv"
        ),
        help=(
            "官方提交文件输出路径，"
            "默认 partB_allocation.csv"
        ),
    )

    parser.add_argument(
        "--audit",
        type=Path,
        default=Path(
            "partB_optimality_audit.csv"
        ),
        help=(
            "最优性/约束诊断 CSV 输出路径"
        ),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.data_dir.exists():
        print(
            f"错误：数据目录不存在："
            f"{args.data_dir}",
            file=sys.stderr,
        )
        return 2

    try:
        run(
            data_dir=args.data_dir,
            allocation_output=args.output,
            audit_output=args.audit,
        )
    except Exception as exc:
        print(
            f"Part B 求解失败：{exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
