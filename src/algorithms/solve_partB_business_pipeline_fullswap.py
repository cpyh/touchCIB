#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能财富管理运营平台 - Part B 业务执行流水线
==========================================

定位
----
本文件是“业务执行层”，与已经验证有效的评分层
solve_partB_python313.py 严格隔离。

流水线：
    Stage 1  理论评分优化
        -> 调用 solve_partB_python313.py
        -> 得到理论最优权重 w*

    Stage 2  起投金额可执行性检查
        -> amount_i = total_amount * weight_i
        -> 检查 amount_i >= min_invest_i

    Stage 3  业务二次分配
        -> 不人为限定最多持仓数
        -> 不设置 Top-K
        -> 不设置 Utility 保留率门槛
        -> 仅加入题目给出的 total_amount / min_invest 业务可执行条件
        -> 固定业务持仓支持集后，所有持仓强制满足起投权重
        -> 对理论低于起投的产品显式比较“不买”与“提升至起投权重”
        -> 使用 ADD / DROP / SWAP 支持集局部搜索反复重优化
        -> 如最低持仓数不足，才做必要的业务可行性修复

    Stage 4  输出最终业务组合与理论/业务对比

业务约束
--------
对于任一最终持仓产品 i：
    amount_i = A * w_i >= min_invest_i

等价于：
    w_i = 0
    或
    w_i >= min_invest_i / A

同时保留原 Part B 的全部约束：
    sum(w) <= 1
    0 <= w_i <= max_single_weight
    R4/R5 总权重 <= max_high_risk_weight
    高流动产品 + 现金 >= min_liquid_weight
    holdings >= min_holdings

重要隔离原则
------------
1. 本程序不会覆盖官方提交用 partB_allocation.csv。
2. 业务输出固定写到 output/business/。
3. 官方评分仍应使用 solve_partB_python313.py 的 Stage 1 输出。
4. 本业务实现采用“固定支持集凸优化 + 循环 ADD/DROP/SWAP 局部搜索”工程算法。
   数学上的精确业务模型可写为 MISOCP；本实现不额外引入商用/混合整数求解器。
   因此：固定支持集内为凸优化高精度解；离散支持集部分属于启发式局部最优搜索。

运行
----
把本文件和 solve_partB_python313.py 放在同一目录：

python solve_partB_business_pipeline_final.py --data-dir data

默认输出
--------
output/business/business_allocation.csv
output/business/business_summary.csv
output/business/business_execution_audit.csv
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, minimize


# ============================================================
# 1. 常量
# ============================================================

RANDOM_STATE = 42

# 官方持仓计数阈值
SCORER_TOL = 1e-6

# 业务金额按“分”展示和校验。
MONEY_TOL = 0.005

# 数值噪声清理
NUMERIC_ZERO = 1e-12

OUTPUT_DECIMALS = 12
MAX_BUSINESS_ITERATIONS = 100

# 离散支持集局部搜索的 Utility 改善阈值。
LOCAL_SEARCH_IMPROVEMENT_TOL = 1e-11

# 最终离线业务结果使用完整 SWAP 邻域。
# 本题只有 30 个产品，因此可对所有“当前持仓 -> 当前未持仓”单产品交换
# 逐一做固定支持集凸优化验证，避免完整交换邻域漏掉有效交换。


# ============================================================
# 2. 导入已验证评分层
# ============================================================

def load_scoring_engine():
    """理论层评分引擎。

    原实现依赖同目录 solve_partB_python313.py；仓库内未随包提供该文件。
    本项目第一阶段的凸优化求解器（src.algorithms.partb）与评分层同名同参、
    已验证 total_U 一致，故直接复用，保证理论口径与提交文件同源。
    """
    from . import partb

    return partb


BASE = load_scoring_engine()


# ============================================================
# 3. 业务数据结构
# ============================================================

@dataclass(frozen=True)
class BusinessProduct:
    product_id: str
    product_name: str
    product_type: str
    risk_level: str
    expected_return: float
    volatility: float
    min_invest: float
    duration_days: int
    liquidity: str


@dataclass
class BusinessSolveResult:
    scenario_id: str
    weights: np.ndarray
    expected_return: float
    portfolio_volatility: float
    utility: float
    cash_weight: float
    holdings_count: int
    high_risk_weight: float
    liquid_plus_cash: float
    iterations: int
    natural_unavailable_ids: list[str]
    initial_below_min_ids: list[str]
    forced_repair_ids: list[str]
    local_search_added_ids: list[str]
    local_search_dropped_ids: list[str]
    move_log: list[str]


# ============================================================
# 4. 读取业务字段
# ============================================================

def read_dict_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))


def load_business_products(
    data_dir: Path,
    expected_product_ids: list[str],
) -> list[BusinessProduct]:
    """
    业务层单独读取 t_product.csv 的完整字段，
    尤其是 min_invest。

    不修改评分层 ProductData，避免两个层次相互污染。
    """
    rows = read_dict_csv(
        data_dir / "t_product.csv"
    )

    product_ids = [
        row["product_id"]
        for row in rows
    ]

    if product_ids != expected_product_ids:
        raise ValueError(
            "业务层产品顺序与评分层产品顺序不一致。"
        )

    result: list[BusinessProduct] = []

    for row in rows:
        result.append(
            BusinessProduct(
                product_id=row["product_id"],
                product_name=row["product_name"],
                product_type=row["product_type"],
                risk_level=row["risk_level"],
                expected_return=float(
                    row["expected_return"]
                ),
                volatility=float(
                    row["volatility"]
                ),
                min_invest=float(
                    row["min_invest"]
                ),
                duration_days=int(
                    float(row["duration_days"])
                ),
                liquidity=row["liquidity"],
            )
        )

    return result


# ============================================================
# 5. 业务约束辅助函数
# ============================================================

def business_min_weights(
    scenario,
    business_products: list[BusinessProduct],
) -> np.ndarray:
    """
    theta_i = min_invest_i / total_amount
    """
    if scenario.total_amount <= 0:
        raise ValueError(
            f"{scenario.scenario_id}: total_amount 必须 > 0。"
        )

    return np.asarray(
        [
            p.min_invest
            / scenario.total_amount
            for p in business_products
        ],
        dtype=float,
    )


def natural_unavailable_mask(
    scenario,
    min_weights: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
) -> np.ndarray:
    """
    在不考虑其他产品的情况下，判断产品是否“天然不可投”。

    若最低起投权重本身就超过任一适用硬上限，则该产品在该场景
    无论如何都不能形成合法持仓。

    例如：
        min_invest / A > max_single_weight
    则天然不可投。
    """
    n = len(min_weights)

    capacity = np.full(
        n,
        scenario.max_single_weight,
        dtype=float,
    )

    # 高风险产品单独持有时也不能突破 R4/R5 总上限。
    capacity[high_risk_mask] = np.minimum(
        capacity[high_risk_mask],
        scenario.max_high_risk_weight,
    )

    # 封闭产品总权重受到 1-min_liquid_weight 上限约束。
    capacity[non_liquid_mask] = np.minimum(
        capacity[non_liquid_mask],
        1.0 - scenario.min_liquid_weight,
    )

    capacity = np.minimum(
        capacity,
        1.0,
    )

    return min_weights > (
        capacity + 1e-12
    )


def build_business_linear_constraint(
    scenario,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    n_products: int,
) -> LinearConstraint:
    """
    与评分层保持相同的三组连续线性约束。
    """
    A = np.vstack(
        [
            np.ones(
                n_products,
                dtype=float,
            ),
            high_risk_mask.astype(float),
            non_liquid_mask.astype(float),
        ]
    )

    upper = np.asarray(
        [
            1.0,
            scenario.max_high_risk_weight,
            1.0
            - scenario.min_liquid_weight,
        ],
        dtype=float,
    )

    lower = np.full(
        3,
        -np.inf,
        dtype=float,
    )

    return LinearConstraint(
        A,
        lower,
        upper,
    )


def find_feasible_start(
    scenario,
    eligible_mask: np.ndarray,
    forced_lower_bounds: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
) -> np.ndarray:
    """
    先用 LP 找一个满足当前支持集上下界的可行点。

    这样业务层即使需要强制某些产品达到起投门槛，
    也不会因为 SLSQP 初值本身不可行而产生不稳定。
    """
    n = len(eligible_mask)

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
            1.0
            - scenario.min_liquid_weight,
        ],
        dtype=float,
    )

    bounds = []

    for i in range(n):
        if eligible_mask[i]:
            lb = float(
                forced_lower_bounds[i]
            )
            ub = float(
                scenario.max_single_weight
            )
        else:
            lb = 0.0
            ub = 0.0

        if lb > ub + 1e-12:
            raise RuntimeError(
                f"{scenario.scenario_id}: "
                "业务下界超过单产品上限。"
            )

        bounds.append(
            (lb, ub)
        )

    lp = linprog(
        c=np.zeros(
            n,
            dtype=float,
        ),
        A_ub=A,
        b_ub=b,
        bounds=bounds,
        method="highs",
    )

    if not lp.success:
        raise RuntimeError(
            f"{scenario.scenario_id}: "
            "当前业务支持集不存在可行权重。"
        )

    return np.asarray(
        lp.x,
        dtype=float,
    )


# ============================================================
# 6. 固定支持集下的精确连续重优化
# ============================================================

def support_lower_bounds(
    min_weights: np.ndarray,
    support_mask: np.ndarray,
) -> np.ndarray:
    """
    对已经决定“购买”的产品，强制满足：

        w_i >= min_invest_i / total_amount

    同时至少略高于官方 1e-6 持仓计数阈值，避免被业务模型选中
    却不被官方 min_holdings 计入。
    """
    lower = np.zeros_like(
        min_weights,
        dtype=float,
    )

    holding_count_floor = (
        SCORER_TOL + 1e-10
    )

    lower[support_mask] = np.maximum(
        min_weights[support_mask],
        holding_count_floor,
    )

    return lower


def solve_fixed_business_support(
    scenario,
    products,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    min_weights: np.ndarray,
    support_mask: np.ndarray,
    preferred_start: np.ndarray | None = None,
    require_min_holdings: bool = True,
) -> tuple[np.ndarray, float]:
    """
    在一个给定的业务持仓支持集上求连续最优权重。

    支持集中的产品：
        w_i >= min_invest_i / total_amount

    支持集外产品：
        w_i = 0

    固定支持集后问题为凸优化。为保证系统运行速度，优先使用上一候选解
    作为 warm start；只有 SLSQP 失败时才调用 LP 生成严格可行初值重试。
    """
    support_mask = np.asarray(support_mask, dtype=bool)
    n = len(products.product_ids)

    if support_mask.shape != (n,):
        raise ValueError(
            f"{scenario.scenario_id}: support_mask 维度错误。"
        )

    support_count = int(np.sum(support_mask))
    if require_min_holdings and support_count < scenario.min_holdings:
        raise RuntimeError(
            f"{scenario.scenario_id}: 固定业务支持集少于 min_holdings。"
        )

    lower = support_lower_bounds(min_weights, support_mask)
    upper = np.where(
        support_mask,
        scenario.max_single_weight,
        0.0,
    )

    if np.any(lower > upper + 1e-12):
        raise RuntimeError(
            f"{scenario.scenario_id}: 起投下界超过单产品上限。"
        )

    bounds = Bounds(lower, upper)
    constraint = build_business_linear_constraint(
        scenario,
        high_risk_mask,
        non_liquid_mask,
        n,
    )

    def run_slsqp(x0: np.ndarray):
        return minimize(
            fun=lambda w: BASE.convex_objective_and_gradient(
                w,
                products.expected_return,
                sigma,
                scenario.risk_aversion,
            )[0],
            x0=x0,
            jac=lambda w: BASE.convex_objective_and_gradient(
                w,
                products.expected_return,
                sigma,
                scenario.risk_aversion,
            )[1],
            method="SLSQP",
            bounds=bounds,
            constraints=[constraint],
            options={
                "ftol": 1e-11,
                "maxiter": 1200,
                "disp": False,
            },
        )

    starts: list[np.ndarray] = []

    if preferred_start is not None:
        x = np.asarray(preferred_start, dtype=float).copy()
        x = np.minimum(np.maximum(x, lower), upper)
        starts.append(x)

    # 一个简单的下界初值非常便宜；SLSQP 可以从线性约束轻微不可行处恢复。
    starts.append(lower.copy())

    best_w: np.ndarray | None = None
    best_u = -np.inf

    for x0 in starts:
        result = run_slsqp(x0)
        if not result.success:
            continue

        w = np.asarray(result.x, dtype=float)
        w[np.abs(w) < NUMERIC_ZERO] = 0.0
        w[w < 0] = 0.0

        # 业务支持集下界和线性约束复核。
        if np.any(w[support_mask] < lower[support_mask] - 2e-7):
            continue

        if float(w.sum()) > 1.0 + 2e-7:
            continue
        if float(w[high_risk_mask].sum()) > scenario.max_high_risk_weight + 2e-7:
            continue
        if float(w[non_liquid_mask].sum()) > 1.0 - scenario.min_liquid_weight + 2e-7:
            continue

        _, _, utility = BASE.portfolio_statistics(
            w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        if utility > best_u:
            best_u = utility
            best_w = w.copy()

    # Warm start 未成功时才调用 HiGHS LP，减少局部搜索中的大量 LP 启动开销。
    if best_w is None:
        feasible_start = find_feasible_start(
            scenario=scenario,
            eligible_mask=support_mask,
            forced_lower_bounds=lower,
            high_risk_mask=high_risk_mask,
            non_liquid_mask=non_liquid_mask,
        )

        result = run_slsqp(feasible_start)

        if result.success:
            w = np.asarray(result.x, dtype=float)
            w[np.abs(w) < NUMERIC_ZERO] = 0.0
            w[w < 0] = 0.0

            if (
                np.all(w[support_mask] >= lower[support_mask] - 2e-7)
                and float(w.sum()) <= 1.0 + 2e-7
                and float(w[high_risk_mask].sum())
                    <= scenario.max_high_risk_weight + 2e-7
                and float(w[non_liquid_mask].sum())
                    <= 1.0 - scenario.min_liquid_weight + 2e-7
            ):
                _, _, best_u = BASE.portfolio_statistics(
                    w,
                    products.expected_return,
                    sigma,
                    scenario.risk_aversion,
                )
                best_w = w.copy()

    if best_w is None:
        raise RuntimeError(
            f"{scenario.scenario_id}: 固定业务支持集连续优化失败。"
        )

    return best_w, float(best_u)


# ============================================================
# 7. 初始业务支持集构造
# ============================================================

def build_initial_business_support(
    scenario,
    theoretical_result,
    products,
    business_products: list[BusinessProduct],
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    min_weights: np.ndarray,
    natural_available: np.ndarray,
) -> tuple[
    np.ndarray,
    np.ndarray,
    list[int],
]:
    """
    初始支持集只保留“理论组合当前就已达到起投金额”的持仓。

    这只是局部搜索的起点，不代表低于起投的产品永久删除。
    后续 ADD / SWAP 搜索会显式尝试：

        w_i = 0
        与
        w_i >= theta_i

    两种业务分支。
    """
    n = len(products.product_ids)

    theoretical_w = np.asarray(
        theoretical_result.weights,
        dtype=float,
    )

    theoretical_amount = (
        scenario.total_amount
        * theoretical_w
    )

    min_invest = np.asarray(
        [
            p.min_invest
            for p in business_products
        ],
        dtype=float,
    )

    theoretical_active = (
        theoretical_w >= SCORER_TOL
    )

    directly_executable = (
        theoretical_active
        & natural_available
        & (
            theoretical_amount
            >= min_invest - MONEY_TOL
        )
    )

    initial_below_min = np.where(
        theoretical_active
        & natural_available
        & ~directly_executable
    )[0].tolist()

    support = directly_executable.copy()

    # 如果理论上直接可执行的产品少于 min_holdings，
    # 则从自然可投产品中逐个寻找最优可行补入项。
    forced_added: list[int] = []

    if int(np.sum(support)) < scenario.min_holdings:
        # 用理论点目标梯度作为候选排序，仅用于减少无意义尝试；
        # 最终每个候选都需要经过完整固定支持集优化验证。
        _, grad = BASE.convex_objective_and_gradient(
            theoretical_w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        candidate_order = np.where(
            natural_available
            & ~support
        )[0]

        candidate_order = candidate_order[
            np.argsort(
                (-grad)[candidate_order]
            )[::-1]
        ]

        # 构造阶段允许中间支持数暂时不足 min_holdings。
        while int(np.sum(support)) < scenario.min_holdings:
            best_candidate = None
            best_w = None
            best_u = -np.inf

            for idx in candidate_order:
                if support[idx]:
                    continue

                trial_support = support.copy()
                trial_support[idx] = True

                try:
                    trial_w, trial_u = solve_fixed_business_support(
                        scenario=scenario,
                        products=products,
                        sigma=sigma,
                        high_risk_mask=high_risk_mask,
                        non_liquid_mask=non_liquid_mask,
                        min_weights=min_weights,
                        support_mask=trial_support,
                        preferred_start=theoretical_w,
                        require_min_holdings=False,
                    )
                except RuntimeError:
                    continue

                if trial_u > best_u:
                    best_u = trial_u
                    best_w = trial_w
                    best_candidate = int(idx)

            if best_candidate is None:
                raise RuntimeError(
                    f"{scenario.scenario_id}: "
                    "起投约束下无法构造满足 min_holdings 的业务支持集。"
                )

            support[best_candidate] = True
            forced_added.append(
                best_candidate
            )

    # 对最终初始支持集做一次正式重优化。
    w, _ = solve_fixed_business_support(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        min_weights=min_weights,
        support_mask=support,
        preferred_start=theoretical_w,
        require_min_holdings=True,
    )

    return (
        support,
        w,
        forced_added,
    )


# ============================================================
# 8. 支持集局部搜索：循环 ADD / DROP / SWAP 至收敛
# ============================================================

def improve_business_support_local_search(
    scenario,
    products,
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
    min_weights: np.ndarray,
    natural_available: np.ndarray,
    initial_support: np.ndarray,
    initial_weights: np.ndarray,
) -> tuple[
    np.ndarray,
    np.ndarray,
    int,
    list[int],
    list[int],
    list[str],
]:
    """
    业务支持集局部搜索（最终工程版）。

    固定支持集内：
        - 持有产品 w_i >= min_invest_i / total_amount
        - 未持有产品 w_i = 0
        - 重新最大化原始 Utility

    离散支持集采用循环邻域搜索：
        ADD -> DROP -> SWAP -> restart

    与上一版的核心区别：
    - DROP 后会重新回到 ADD，直到一整轮没有改善；
    - 不会出现“前面 ADD 扫描结束，后面 DROP 后又产生新的 ADD 机会却漏掉”的问题；
    - SWAP 不再使用候选短名单，而是完整扫描全部单产品交换邻域。

    ADD/DROP 使用 first-improvement：
    候选按照一阶边际方向/当前小权重进行排序，一旦找到真实 Utility 改善
    就接受并立即 restart。若 ADD 与 DROP 均无改善，则完整扫描所有合法
    DROP×ADD 单产品 SWAP。只有完整 ADD、DROP、SWAP 邻域均无改善时才终止。

    注意：离散部分仍是 MISOCP 的启发式搜索，不宣称全局最优。
    """
    support = np.asarray(initial_support, dtype=bool).copy()
    current_w = np.asarray(initial_weights, dtype=float).copy()

    _, _, current_u = BASE.portfolio_statistics(
        current_w,
        products.expected_return,
        sigma,
        scenario.risk_aversion,
    )

    added_history: list[int] = []
    dropped_history: list[int] = []
    move_log: list[str] = []

    def try_support(
        trial_support: np.ndarray,
    ) -> tuple[np.ndarray, float] | None:
        if int(np.sum(trial_support)) < scenario.min_holdings:
            return None

        if np.any(trial_support & ~natural_available):
            return None

        try:
            return solve_fixed_business_support(
                scenario=scenario,
                products=products,
                sigma=sigma,
                high_risk_mask=high_risk_mask,
                non_liquid_mask=non_liquid_mask,
                min_weights=min_weights,
                support_mask=trial_support,
                preferred_start=current_w,
                require_min_holdings=True,
            )
        except RuntimeError:
            return None

    def accept_move(
        move_type: str,
        trial_support: np.ndarray,
        trial_w: np.ndarray,
        trial_u: float,
        add_idx: int | None = None,
        drop_idx: int | None = None,
    ) -> None:
        nonlocal support, current_w, current_u

        old_u = current_u
        support = trial_support
        current_w = trial_w
        current_u = trial_u

        if add_idx is not None:
            added_history.append(int(add_idx))
        if drop_idx is not None:
            dropped_history.append(int(drop_idx))

        if move_type == "ADD":
            detail = f"add={products.product_ids[add_idx]}"
        elif move_type == "DROP":
            detail = f"drop={products.product_ids[drop_idx]}"
        else:
            detail = (
                f"drop={products.product_ids[drop_idx]}, "
                f"add={products.product_ids[add_idx]}"
            )

        move_log.append(
            f"{move_type}: {detail}, "
            f"U {old_u:.12f} -> {current_u:.12f}, "
            f"delta={current_u - old_u:+.3e}"
        )

    iterations = 0

    while iterations < MAX_BUSINESS_ITERATIONS:
        iterations += 1
        moved = False

        # ----------------------------------------------------
        # A. ADD：按当前目标的一阶边际方向排序，first improvement
        # ----------------------------------------------------
        _, grad = BASE.convex_objective_and_gradient(
            current_w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        add_candidates = np.where(
            natural_available & ~support
        )[0]

        add_candidates = add_candidates[
            np.argsort((-grad)[add_candidates])[::-1]
        ]

        for idx in add_candidates:
            trial_support = support.copy()
            trial_support[idx] = True

            evaluated = try_support(trial_support)
            if evaluated is None:
                continue

            trial_w, trial_u = evaluated

            if trial_u > current_u + LOCAL_SEARCH_IMPROVEMENT_TOL:
                accept_move(
                    "ADD",
                    trial_support,
                    trial_w,
                    trial_u,
                    add_idx=int(idx),
                )
                moved = True
                break

        if moved:
            continue

        # ----------------------------------------------------
        # B. DROP：优先尝试当前较小权重持仓，first improvement
        # ----------------------------------------------------
        if int(np.sum(support)) > scenario.min_holdings:
            drop_candidates = np.where(support)[0]
            drop_candidates = drop_candidates[
                np.argsort(current_w[drop_candidates])
            ]

            for idx in drop_candidates:
                trial_support = support.copy()
                trial_support[idx] = False

                evaluated = try_support(trial_support)
                if evaluated is None:
                    continue

                trial_w, trial_u = evaluated

                if trial_u > current_u + LOCAL_SEARCH_IMPROVEMENT_TOL:
                    accept_move(
                        "DROP",
                        trial_support,
                        trial_w,
                        trial_u,
                        drop_idx=int(idx),
                    )
                    moved = True
                    break

        if moved:
            # 关键：DROP 后立即回到 ADD。
            continue

        # ----------------------------------------------------
        # C. SWAP：完整单产品交换邻域 + first improvement
        # ----------------------------------------------------
        # ADD 端仍按当前一阶边际方向排序，只影响“先试谁”，
        # 不影响完整性：所有未持仓且业务可投资产品都会被检查。
        _, grad = BASE.convex_objective_and_gradient(
            current_w,
            products.expected_return,
            sigma,
            scenario.risk_aversion,
        )

        add_candidates = np.where(
            natural_available & ~support
        )[0]
        add_candidates = add_candidates[
            np.argsort((-grad)[add_candidates])[::-1]
        ]

        # DROP 端按当前权重从小到大排序，同样只影响搜索顺序。
        drop_candidates = np.where(support)[0]
        drop_candidates = drop_candidates[
            np.argsort(current_w[drop_candidates])
        ]

        for drop_idx in drop_candidates:
            for add_idx in add_candidates:
                trial_support = support.copy()
                trial_support[drop_idx] = False
                trial_support[add_idx] = True

                evaluated = try_support(trial_support)
                if evaluated is None:
                    continue

                trial_w, trial_u = evaluated

                if trial_u > current_u + LOCAL_SEARCH_IMPROVEMENT_TOL:
                    accept_move(
                        "SWAP",
                        trial_support,
                        trial_w,
                        trial_u,
                        add_idx=int(add_idx),
                        drop_idx=int(drop_idx),
                    )
                    moved = True
                    break

            if moved:
                break

        if moved:
            # 任一 SWAP 被接受后，支持集已改变，重新从 ADD 开始。
            continue

        move_log.append(
            "CONVERGED: no improving ADD/DROP/SWAP move "
            f"above {LOCAL_SEARCH_IMPROVEMENT_TOL:.1e}; "
            f"final U={current_u:.12f}"
        )
        break

    else:
        move_log.append(
            "STOP: reached MAX_BUSINESS_ITERATIONS="
            f"{MAX_BUSINESS_ITERATIONS}; "
            f"final U={current_u:.12f}"
        )

    # 最后对最终支持集再做一次正式高精度重优化。
    final_w, _ = solve_fixed_business_support(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        min_weights=min_weights,
        support_mask=support,
        preferred_start=current_w,
        require_min_holdings=True,
    )

    return (
        support,
        final_w,
        iterations,
        added_history,
        dropped_history,
        move_log,
    )


# ============================================================
# 9. 单场景业务流水线
# ============================================================

def solve_business_scenario(
    scenario,
    theoretical_result,
    products,
    business_products: list[BusinessProduct],
    sigma: np.ndarray,
    high_risk_mask: np.ndarray,
    non_liquid_mask: np.ndarray,
) -> BusinessSolveResult:
    min_weights = business_min_weights(
        scenario,
        business_products,
    )

    natural_unavailable = natural_unavailable_mask(
        scenario,
        min_weights,
        high_risk_mask,
        non_liquid_mask,
    )

    natural_available = ~natural_unavailable

    theoretical_w = np.asarray(
        theoretical_result.weights,
        dtype=float,
    )

    theoretical_amount = (
        scenario.total_amount
        * theoretical_w
    )

    min_invest = np.asarray(
        [
            p.min_invest
            for p in business_products
        ],
        dtype=float,
    )

    initial_below_min = np.where(
        (theoretical_w >= SCORER_TOL)
        & natural_available
        & (
            theoretical_amount
            < min_invest - MONEY_TOL
        )
    )[0].tolist()

    (
        initial_support,
        initial_w,
        forced_added,
    ) = build_initial_business_support(
        scenario=scenario,
        theoretical_result=theoretical_result,
        products=products,
        business_products=business_products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        min_weights=min_weights,
        natural_available=natural_available,
    )

    (
        final_support,
        w,
        search_iterations,
        added_history,
        dropped_history,
        move_log,
    ) = improve_business_support_local_search(
        scenario=scenario,
        products=products,
        sigma=sigma,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        min_weights=min_weights,
        natural_available=natural_available,
        initial_support=initial_support,
        initial_weights=initial_w,
    )

    # --------------------------------------------------------
    # 最终独立校验：原 Part B 全部硬约束
    # --------------------------------------------------------
    official_checks = BASE.validate_solution(
        scenario,
        w,
        high_risk_mask,
        non_liquid_mask,
    )

    if not all(
        official_checks.values()
    ):
        failed = [
            k
            for k, v
            in official_checks.items()
            if not v
        ]

        raise RuntimeError(
            f"{scenario.scenario_id}: "
            f"业务结果违反原 Part B 约束：{failed}"
        )

    # --------------------------------------------------------
    # 最终独立校验：所有业务持仓达到起投门槛
    # --------------------------------------------------------
    for i, weight in enumerate(w):
        if weight < SCORER_TOL:
            continue

        amount = (
            scenario.total_amount
            * weight
        )

        if (
            amount
            < business_products[i].min_invest
            - MONEY_TOL
        ):
            raise RuntimeError(
                f"{scenario.scenario_id}/"
                f"{products.product_ids[i]}: "
                "最终业务结果仍低于起投金额。"
            )

    (
        expected_return,
        portfolio_volatility,
        utility,
    ) = BASE.portfolio_statistics(
        w,
        products.expected_return,
        sigma,
        scenario.risk_aversion,
    )

    cash_weight = 1.0 - float(
        w.sum()
    )

    high_risk_weight = float(
        w[high_risk_mask].sum()
    )

    liquid_plus_cash = float(
        w[~non_liquid_mask].sum()
        + cash_weight
    )

    holdings_count = int(
        np.sum(
            w >= SCORER_TOL
        )
    )

    # 历史 move 中 ADD 后又被 DROP 的产品不应在“最终新增”里重复计入。
    theoretical_support = (
        theoretical_w >= SCORER_TOL
    )

    final_added = np.where(
        final_support
        & ~theoretical_support
    )[0]

    final_dropped = np.where(
        theoretical_support
        & ~final_support
        & natural_available
    )[0]

    return BusinessSolveResult(
        scenario_id=scenario.scenario_id,
        weights=w,
        expected_return=expected_return,
        portfolio_volatility=portfolio_volatility,
        utility=utility,
        cash_weight=cash_weight,
        holdings_count=holdings_count,
        high_risk_weight=high_risk_weight,
        liquid_plus_cash=liquid_plus_cash,
        iterations=search_iterations,
        natural_unavailable_ids=[
            products.product_ids[i]
            for i in np.where(
                natural_unavailable
            )[0]
        ],
        initial_below_min_ids=[
            products.product_ids[i]
            for i in initial_below_min
        ],
        forced_repair_ids=[
            products.product_ids[i]
            for i in forced_added
        ],
        local_search_added_ids=[
            products.product_ids[i]
            for i in final_added
        ],
        local_search_dropped_ids=[
            products.product_ids[i]
            for i in final_dropped
        ],
        move_log=move_log,
    )


# ============================================================
# 9. 输出文件
# ============================================================

def write_business_allocation(
    path: Path,
    scenarios,
    products,
    business_products: list[BusinessProduct],
    theoretical_map,
    business_map: dict[
        str,
        BusinessSolveResult,
    ],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fields = [
        "scenario_id",
        "product_id",
        "product_name",
        "weight",
        "amount",
        "min_invest",
        "meets_min_invest",
        "risk_level",
        "liquidity",
        "expected_return",
        "volatility",
        "theoretical_weight",
        "theoretical_amount",
        "weight_change",
    ]

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for scenario in scenarios:
            theoretical = (
                theoretical_map[
                    scenario.scenario_id
                ]
            )

            business = (
                business_map[
                    scenario.scenario_id
                ]
            )

            for i, (
                pid,
                bp,
            ) in enumerate(
                zip(
                    products.product_ids,
                    business_products,
                )
            ):
                weight = float(
                    business.weights[i]
                )

                if weight < SCORER_TOL:
                    continue

                amount = (
                    scenario.total_amount
                    * weight
                )

                theoretical_weight = float(
                    theoretical.weights[i]
                )

                theoretical_amount = (
                    scenario.total_amount
                    * theoretical_weight
                )

                writer.writerow(
                    {
                        "scenario_id":
                            scenario.scenario_id,

                        "product_id":
                            pid,

                        "product_name":
                            bp.product_name,

                        "weight":
                            f"{weight:.12f}",

                        "amount":
                            f"{amount:.2f}",

                        "min_invest":
                            f"{bp.min_invest:.2f}",

                        "meets_min_invest":
                            (
                                amount
                                >= bp.min_invest
                                - MONEY_TOL
                            ),

                        "risk_level":
                            bp.risk_level,

                        "liquidity":
                            bp.liquidity,

                        "expected_return":
                            f"{bp.expected_return:.8f}",

                        "volatility":
                            f"{bp.volatility:.8f}",

                        "theoretical_weight":
                            f"{theoretical_weight:.12f}",

                        "theoretical_amount":
                            f"{theoretical_amount:.2f}",

                        "weight_change":
                            f"{weight - theoretical_weight:+.12f}",
                    }
                )


def write_business_summary(
    path: Path,
    scenarios,
    business_products: list[BusinessProduct],
    theoretical_map,
    business_map: dict[
        str,
        BusinessSolveResult,
    ],
) -> None:
    fields = [
        "scenario_id",
        "total_amount",
        "lambda",
        "theoretical_utility",
        "business_utility",
        "utility_loss",
        "utility_retention_ratio",
        "theoretical_expected_return",
        "business_expected_return",
        "theoretical_volatility",
        "business_volatility",
        "theoretical_holdings",
        "business_holdings",
        "theoretical_min_invest_violations",
        "natural_unavailable_products",
        "initial_below_min_products",
        "final_local_search_added_products",
        "final_local_search_dropped_products",
        "forced_min_holdings_repairs",
        "local_search_move_count",
        "business_cash_weight",
        "business_cash_amount",
        "business_high_risk_weight",
        "business_liquid_plus_cash",
        "iterations",
        "all_min_invest_satisfied",
        "all_official_constraints_satisfied",
    ]

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for scenario in scenarios:
            theoretical = (
                theoretical_map[
                    scenario.scenario_id
                ]
            )

            business = (
                business_map[
                    scenario.scenario_id
                ]
            )

            theory_amounts = (
                scenario.total_amount
                * theoretical.weights
            )

            min_invest = np.asarray(
                [
                    p.min_invest
                    for p
                    in business_products
                ],
                dtype=float,
            )

            theory_active = (
                theoretical.weights
                >= SCORER_TOL
            )

            theory_violations = int(
                np.sum(
                    theory_active
                    & (
                        theory_amounts
                        < min_invest
                        - MONEY_TOL
                    )
                )
            )

            utility_loss = (
                theoretical.utility
                - business.utility
            )

            retention = (
                business.utility
                / theoretical.utility
                if abs(
                    theoretical.utility
                ) > 1e-15
                else math.nan
            )

            official_checks = (
                BASE.validate_solution(
                    scenario,
                    business.weights,
                    np.isin(
                        np.asarray(
                            [
                                p.risk_level
                                for p
                                in business_products
                            ],
                            dtype=object,
                        ),
                        ["R4", "R5"],
                    ),
                    np.asarray(
                        [
                            p.liquidity
                            == "封闭"
                            for p
                            in business_products
                        ],
                        dtype=bool,
                    ),
                )
            )

            all_min_invest = True

            for i, weight in enumerate(
                business.weights
            ):
                if weight < SCORER_TOL:
                    continue

                amount = (
                    scenario.total_amount
                    * weight
                )

                if (
                    amount
                    < min_invest[i]
                    - MONEY_TOL
                ):
                    all_min_invest = False
                    break

            writer.writerow(
                {
                    "scenario_id":
                        scenario.scenario_id,

                    "total_amount":
                        f"{scenario.total_amount:.2f}",

                    "lambda":
                        f"{scenario.risk_aversion:.8f}",

                    "theoretical_utility":
                        f"{theoretical.utility:.15f}",

                    "business_utility":
                        f"{business.utility:.15f}",

                    "utility_loss":
                        f"{utility_loss:.15f}",

                    "utility_retention_ratio":
                        f"{retention:.8f}",

                    "theoretical_expected_return":
                        f"{theoretical.expected_return:.12f}",

                    "business_expected_return":
                        f"{business.expected_return:.12f}",

                    "theoretical_volatility":
                        f"{theoretical.portfolio_volatility:.12f}",

                    "business_volatility":
                        f"{business.portfolio_volatility:.12f}",

                    "theoretical_holdings":
                        theoretical.holdings_count,

                    "business_holdings":
                        business.holdings_count,

                    "theoretical_min_invest_violations":
                        theory_violations,

                    "natural_unavailable_products":
                        len(
                            business.natural_unavailable_ids
                        ),

                    "initial_below_min_products":
                        len(
                            business.initial_below_min_ids
                        ),

                    "final_local_search_added_products":
                        len(
                            business.local_search_added_ids
                        ),

                    "final_local_search_dropped_products":
                        len(
                            business.local_search_dropped_ids
                        ),

                    "forced_min_holdings_repairs":
                        len(
                            business.forced_repair_ids
                        ),

                    "local_search_move_count":
                        len(business.move_log),

                    "business_cash_weight":
                        f"{business.cash_weight:.12f}",

                    "business_cash_amount":
                        f"{scenario.total_amount * business.cash_weight:.2f}",

                    "business_high_risk_weight":
                        f"{business.high_risk_weight:.12f}",

                    "business_liquid_plus_cash":
                        f"{business.liquid_plus_cash:.12f}",

                    "iterations":
                        business.iterations,

                    "all_min_invest_satisfied":
                        all_min_invest,

                    "all_official_constraints_satisfied":
                        all(
                            official_checks.values()
                        ),
                }
            )


def write_execution_audit(
    path: Path,
    scenarios,
    products,
    business_products: list[BusinessProduct],
    theoretical_map,
    business_map: dict[
        str,
        BusinessSolveResult,
    ],
) -> None:
    """
    给前端/答辩解释为什么某个产品被保留、调整或排除。
    """
    fields = [
        "scenario_id",
        "product_id",
        "product_name",
        "min_invest",
        "min_required_weight",
        "theoretical_weight",
        "theoretical_amount",
        "business_weight",
        "business_amount",
        "business_status",
        "business_reason",
    ]

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for scenario in scenarios:
            theoretical = theoretical_map[
                scenario.scenario_id
            ]

            business = business_map[
                scenario.scenario_id
            ]

            natural_set = set(
                business.natural_unavailable_ids
            )

            below_min_set = set(
                business.initial_below_min_ids
            )

            added_set = set(
                business.local_search_added_ids
            )

            dropped_set = set(
                business.local_search_dropped_ids
            )

            forced_set = set(
                business.forced_repair_ids
            )

            for i, (
                pid,
                bp,
            ) in enumerate(
                zip(
                    products.product_ids,
                    business_products,
                )
            ):
                tw = float(
                    theoretical.weights[i]
                )

                bw = float(
                    business.weights[i]
                )

                ta = (
                    scenario.total_amount
                    * tw
                )

                ba = (
                    scenario.total_amount
                    * bw
                )

                if pid in natural_set:
                    status = "EXCLUDED"
                    reason = (
                        "起投权重高于该场景适用硬上限，天然不可投资"
                    )

                elif pid in forced_set:
                    status = "HELD"
                    reason = (
                        "为满足原题 min_holdings，在可行条件下补入并满足起投金额"
                    )

                elif bw >= SCORER_TOL:
                    status = "HELD"

                    if pid in added_set:
                        reason = (
                            "支持集局部搜索 ADD 搜索后进入最终组合，并强制满足起投金额"
                        )
                    elif pid in below_min_set:
                        reason = (
                            "理论金额原低于起投门槛；业务搜索比较 w=0 与 w>=起投权重后选择保留"
                        )
                    elif (
                        tw >= SCORER_TOL
                        and ta
                        >= bp.min_invest
                        - MONEY_TOL
                    ):
                        reason = (
                            "理论持仓可直接执行，并在固定支持集重优化后保留"
                        )
                    else:
                        reason = (
                            "业务支持集搜索后进入最终组合，并满足起投金额"
                        )

                else:
                    status = "NOT_HELD"

                    if pid in dropped_set:
                        reason = (
                            "支持集局部搜索 DROP 搜索后不再持有；删除后组合 Utility 更高"
                        )
                    elif pid in below_min_set:
                        reason = (
                            "理论金额低于起投门槛；业务搜索比较提升至起投权重与不持有后，选择不持有"
                        )
                    else:
                        reason = (
                            "在 ADD/DROP 邻域搜索后未进入最终业务组合"
                        )

                writer.writerow(
                    {
                        "scenario_id":
                            scenario.scenario_id,

                        "product_id":
                            pid,

                        "product_name":
                            bp.product_name,

                        "min_invest":
                            f"{bp.min_invest:.2f}",

                        "min_required_weight":
                            f"{bp.min_invest / scenario.total_amount:.12f}",

                        "theoretical_weight":
                            f"{tw:.12f}",

                        "theoretical_amount":
                            f"{ta:.2f}",

                        "business_weight":
                            f"{bw:.12f}",

                        "business_amount":
                            f"{ba:.2f}",

                        "business_status":
                            status,

                        "business_reason":
                            reason,
                    }
                )


# ============================================================
# 10. 完整业务流水线
# ============================================================

def run_business_pipeline(
    data_dir: Path,
    output_dir: Path,
) -> None:
    # ---------- 共用输入 ----------
    products = BASE.load_products(
        data_dir
    )

    scenarios = BASE.load_scenarios(
        data_dir
    )

    corr = (
        BASE.load_correlation_matrix(
            data_dir,
            products.product_ids,
        )
    )

    sigma = (
        BASE.build_covariance_matrix(
            products.volatility,
            corr,
        )
    )

    BASE.check_covariance_matrix(
        sigma
    )

    (
        high_risk_mask,
        non_liquid_mask,
    ) = BASE.build_masks(
        products
    )

    business_products = (
        load_business_products(
            data_dir,
            products.product_ids,
        )
    )

    # ========================================================
    # Stage 1：理论评分优化
    # ========================================================
    theoretical_map = {}

    rng = np.random.default_rng(
        RANDOM_STATE
    )

    print("=" * 92)
    print(
        "Part B 理论最优 -> 业务可执行 二阶段流水线"
    )
    print("=" * 92)
    print(
        "Stage 1/4：调用已验证评分层，计算理论最优组合..."
    )

    for scenario in scenarios:
        theoretical_map[
            scenario.scenario_id
        ] = BASE.solve_one_scenario(
            scenario=scenario,
            products=products,
            sigma=sigma,
            high_risk_mask=high_risk_mask,
            non_liquid_mask=non_liquid_mask,
            rng=rng,
        )

    # ========================================================
    # Stage 2 + 3：检查起投并二次优化
    # ========================================================
    print(
        "Stage 2/4：检查 total_amount / min_invest..."
    )
    print(
        "Stage 3/4：进行业务支持集迭代重优化..."
    )
    print("-" * 92)

    business_map: dict[
        str,
        BusinessSolveResult,
    ] = {}

    total_theory_u = 0.0
    total_business_u = 0.0

    for scenario in scenarios:
        theoretical = theoretical_map[
            scenario.scenario_id
        ]

        business = solve_business_scenario(
            scenario=scenario,
            theoretical_result=theoretical,
            products=products,
            business_products=business_products,
            sigma=sigma,
            high_risk_mask=high_risk_mask,
            non_liquid_mask=non_liquid_mask,
        )

        business_map[
            scenario.scenario_id
        ] = business

        total_theory_u += (
            theoretical.utility
        )

        total_business_u += (
            business.utility
        )

        print(
            f"{scenario.scenario_id} | "
            f"A={scenario.total_amount:>10,.0f} | "
            f"theory_h={theoretical.holdings_count:>2d} -> "
            f"business_h={business.holdings_count:>2d} | "
            f"U={theoretical.utility:.9f} -> "
            f"{business.utility:.9f} | "
            f"moves={len(business.move_log):>2d} | "
            f"natural_block={len(business.natural_unavailable_ids):>2d} | "
            f"iter={business.iterations}"
        )

    # ========================================================
    # Stage 4：输出
    # ========================================================
    print("-" * 92)
    print(
        "Stage 4/4：输出业务组合、摘要和执行审计..."
    )

    allocation_path = (
        output_dir
        / "business_allocation.csv"
    )

    summary_path = (
        output_dir
        / "business_summary.csv"
    )

    audit_path = (
        output_dir
        / "business_execution_audit.csv"
    )

    write_business_allocation(
        allocation_path,
        scenarios,
        products,
        business_products,
        theoretical_map,
        business_map,
    )

    write_business_summary(
        summary_path,
        scenarios,
        business_products,
        theoretical_map,
        business_map,
    )

    write_execution_audit(
        audit_path,
        scenarios,
        products,
        business_products,
        theoretical_map,
        business_map,
    )

    print("=" * 92)
    print(
        f"理论层 total Utility : "
        f"{total_theory_u:.15f}"
    )
    print(
        f"业务层 total Utility : "
        f"{total_business_u:.15f}"
    )
    print(
        f"业务可执行性成本     : "
        f"{total_theory_u - total_business_u:.15f}"
    )
    print(
        f"业务 Utility 保留率 : "
        f"{total_business_u / total_theory_u:.4%}"
    )
    print("-" * 92)
    print(
        f"业务配置明细         : {allocation_path}"
    )
    print(
        f"理论/业务场景摘要    : {summary_path}"
    )
    print(
        f"产品执行审计         : {audit_path}"
    )
    print("=" * 92)
    print(
        "流水线完成：评分层结果未被覆盖；业务结果已单独输出。"
    )


# ============================================================
# 11. CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Part B 理论最优 -> "
            "起投金额检查 -> "
            "业务二次分配流水线"
        )
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help=(
            "包含 t_product.csv、"
            "partB_scenarios.csv、"
            "partB_corr_matrix.csv 的 data 目录"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "output/business"
        ),
        help=(
            "业务输出目录；"
            "默认 output/business"
        ),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        run_business_pipeline(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(
            f"业务流水线失败：{exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
