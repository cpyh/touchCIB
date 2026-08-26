"""Flask API 与组合优化器的适配层：在线优化 + 场景配置存取。"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pymysql

from .algorithms.partb import (
    RANDOM_STATE,
    SCORER_TOL,
    ProductData,
    Scenario,
    build_covariance_matrix,
    build_masks,
    check_covariance_matrix,
    solve_one_scenario,
)

from .database import database_connection

PROJECT_DIR = Path(__file__).resolve().parents[1]


class PortfolioInputError(ValueError):
    """Raised when an API parameter is missing or invalid."""


@lru_cache(maxsize=1)
def optimizer_context() -> tuple[
    ProductData,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    dict[str, dict[str, object]],
]:
    """Load and validate the MySQL-backed product universe once per process."""
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT product_id, product_name, product_type, risk_level, "
                    "expected_return, volatility, liquidity "
                    "FROM dwd_dim_product ORDER BY product_id"
                )
                product_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT product_id, related_product_id, correlation "
                    "FROM ref_product_correlation"
                )
                correlation_rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise RuntimeError("unable to load portfolio inputs from MySQL") from exc

    if not product_rows:
        raise RuntimeError("dwd_dim_product is empty")

    product_ids = [row["product_id"] for row in product_rows]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("dwd_dim_product contains duplicate product IDs")

    products = ProductData(
        product_ids=product_ids,
        expected_return=np.asarray(
            [float(row["expected_return"]) for row in product_rows], dtype=float
        ),
        volatility=np.asarray(
            [float(row["volatility"]) for row in product_rows], dtype=float
        ),
        risk_level=np.asarray(
            [row["risk_level"] for row in product_rows], dtype=object
        ),
        liquidity=np.asarray(
            [row["liquidity"] for row in product_rows], dtype=object
        ),
    )

    product_indexes = {
        product_id: index for index, product_id in enumerate(product_ids)
    }
    correlation = np.full((len(product_ids), len(product_ids)), np.nan)
    for row in correlation_rows:
        product_id = row["product_id"]
        related_product_id = row["related_product_id"]
        if (
            product_id not in product_indexes
            or related_product_id not in product_indexes
        ):
            raise ValueError("ref_product_correlation contains an unknown product ID")
        correlation[
            product_indexes[product_id], product_indexes[related_product_id]
        ] = float(row["correlation"])

    if np.isnan(correlation).any():
        raise ValueError("ref_product_correlation is incomplete")

    covariance = build_covariance_matrix(products.volatility, correlation)
    check_covariance_matrix(covariance)
    high_risk_mask, non_liquid_mask = build_masks(products)
    product_details = {row["product_id"]: row for row in product_rows}
    return (
        products,
        covariance,
        high_risk_mask,
        non_liquid_mask,
        product_details,
    )


def number_param(
    payload: dict,
    name: str,
    *,
    minimum: float,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PortfolioInputError(f"{name} must be a number")

    number = float(value)
    if not math.isfinite(number):
        raise PortfolioInputError(f"{name} must be finite")
    if minimum_inclusive and number < minimum:
        raise PortfolioInputError(f"{name} must be at least {minimum}")
    if not minimum_inclusive and number <= minimum:
        raise PortfolioInputError(f"{name} must be greater than {minimum}")
    if maximum is not None and number > maximum:
        raise PortfolioInputError(f"{name} must be at most {maximum}")
    return number


def optimize_portfolio(payload: dict) -> dict:
    """Optimize one custom scenario and return a JSON-ready result."""
    products, covariance, high_risk_mask, non_liquid_mask, details = (
        optimizer_context()
    )

    total_amount = number_param(
        payload,
        "total_amount",
        minimum=0,
        minimum_inclusive=False,
    )
    risk_aversion = number_param(payload, "risk_aversion", minimum=0)
    max_single_weight = number_param(
        payload,
        "max_single_weight",
        minimum=0,
        maximum=1,
        minimum_inclusive=False,
    )
    max_high_risk_weight = number_param(
        payload,
        "max_high_risk_weight",
        minimum=0,
        maximum=1,
    )
    min_liquid_weight = number_param(
        payload,
        "min_liquid_weight",
        minimum=0,
        maximum=1,
    )

    min_holdings = payload.get("min_holdings")
    if isinstance(min_holdings, bool) or not isinstance(min_holdings, int):
        raise PortfolioInputError("min_holdings must be an integer")
    if not 1 <= min_holdings <= len(products.product_ids):
        raise PortfolioInputError(
            f"min_holdings must be between 1 and {len(products.product_ids)}"
        )

    scenario = Scenario(
        scenario_id="custom",
        total_amount=total_amount,
        risk_aversion=risk_aversion,
        max_single_weight=max_single_weight,
        max_high_risk_weight=max_high_risk_weight,
        min_liquid_weight=min_liquid_weight,
        min_holdings=min_holdings,
    )

    result = solve_one_scenario(
        scenario=scenario,
        products=products,
        sigma=covariance,
        high_risk_mask=high_risk_mask,
        non_liquid_mask=non_liquid_mask,
        rng=np.random.default_rng(RANDOM_STATE),
    )

    allocations = []
    for index, weight in enumerate(result.weights):
        if weight < SCORER_TOL:
            continue
        product_id = products.product_ids[index]
        product = details[product_id]
        allocations.append(
            {
                "product_id": product_id,
                "product_name": product["product_name"],
                "product_type": product["product_type"],
                "risk_level": product["risk_level"],
                "liquidity": product["liquidity"],
                "weight": round(float(weight), 12),
                "amount": round(total_amount * float(weight), 2),
            }
        )
    allocations.sort(key=lambda item: item["weight"], reverse=True)

    # ---- 业务可执行层：理论最优 → 起投金额二次校正（失败不阻断理论路径）----
    business = None
    try:
        from .algorithms.solve_partB_business_pipeline_fullswap import (
            load_business_products,
            solve_business_scenario,
        )

        business_products = load_business_products(
            PROJECT_DIR / "src" / "data" / "raw",
            products.product_ids,
        )
        business_result = solve_business_scenario(
            scenario,
            result,
            products,
            business_products,
            covariance,
            high_risk_mask,
            non_liquid_mask,
        )
        business_allocations = []
        for index, weight in enumerate(business_result.weights):
            if weight < SCORER_TOL:
                continue
            product_id = products.product_ids[index]
            business_allocations.append(
                {
                    "product_id": product_id,
                    "product_name": business_products[index].product_name,
                    "min_invest": business_products[index].min_invest,
                    "weight": round(float(weight), 12),
                    "amount": round(total_amount * float(weight), 2),
                }
            )
        business_allocations.sort(key=lambda item: item["weight"], reverse=True)
        business = {
            "utility": round(business_result.utility, 12),
            "retention_ratio": round(
                business_result.utility / result.utility, 6
            ) if result.utility else None,
            "expected_return": round(business_result.expected_return, 12),
            "portfolio_volatility": round(
                business_result.portfolio_volatility, 12
            ),
            "cash_weight": round(business_result.cash_weight, 12),
            "cash_amount": round(total_amount * business_result.cash_weight, 2),
            "holdings_count": business_result.holdings_count,
            "high_risk_weight": round(business_result.high_risk_weight, 12),
            "liquid_plus_cash": round(business_result.liquid_plus_cash, 12),
            "allocations": business_allocations,
        }
    except Exception:  # noqa: BLE001 - 业务层失败不影响理论最优结果
        business = None

    invested_weight = float(result.weights.sum())
    return {
        "scenario": {
            "total_amount": total_amount,
            "risk_aversion": risk_aversion,
            "max_single_weight": max_single_weight,
            "max_high_risk_weight": max_high_risk_weight,
            "min_liquid_weight": min_liquid_weight,
            "min_holdings": min_holdings,
        },
        "summary": {
            "utility": round(result.utility, 12),
            "expected_return": round(result.expected_return, 12),
            "portfolio_volatility": round(result.portfolio_volatility, 12),
            "invested_weight": round(invested_weight, 12),
            "invested_amount": round(total_amount * invested_weight, 2),
            "cash_weight": round(result.cash_weight, 12),
            "cash_amount": round(total_amount * result.cash_weight, 2),
            "holdings_count": result.holdings_count,
            "high_risk_weight": round(result.high_risk_weight, 12),
            "liquid_plus_cash": round(result.liquid_plus_cash, 12),
            "optimality_gap": result.absolute_gap,
        },
        "allocations": allocations,
        "business": business,
    }


# ------------------------------------------------------------------
# 场景配置存取（原 src/scenario.py，与组合优化同源，已并入本模块）
# ------------------------------------------------------------------

from datetime import date, datetime  # noqa: E402
from decimal import Decimal  # noqa: E402
from uuid import uuid4  # noqa: E402

SCENARIO_COLUMNS = """
    scenario_id, scenario_name, scenario_type, total_amount,
    risk_aversion, max_single_weight, max_high_risk_weight,
    min_liquid_weight, min_holdings, created_at, updated_at
"""


class ScenarioInputError(ValueError):
    """Raised when a custom scenario is invalid."""


class ScenarioStoreError(RuntimeError):
    """Raised when scenario data cannot be accessed."""


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _scenario_json(row: dict) -> dict:
    return {key: _json_value(value) for key, value in row.items()}


def _scenario_number_param(
    payload: dict,
    name: str,
    *,
    minimum: float,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    """共享校验逻辑，错误类型转译为 ScenarioInputError。"""
    try:
        return number_param(
            payload,
            name,
            minimum=minimum,
            maximum=maximum,
            minimum_inclusive=minimum_inclusive,
        )
    except PortfolioInputError as exc:
        raise ScenarioInputError(str(exc)) from exc


def scenario_values(payload: dict, *, max_holdings: int) -> dict[str, object]:
    name = payload.get("scenario_name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioInputError("scenario_name must be a non-empty string")
    if len(name.strip()) > 128:
        raise ScenarioInputError("scenario_name must be at most 128 characters")

    min_holdings = payload.get("min_holdings")
    if isinstance(min_holdings, bool) or not isinstance(min_holdings, int):
        raise ScenarioInputError("min_holdings must be an integer")
    if not 1 <= min_holdings <= max_holdings:
        raise ScenarioInputError(
            f"min_holdings must be between 1 and {max_holdings}"
        )

    return {
        "scenario_name": name.strip(),
        "total_amount": _scenario_number_param(
            payload, "total_amount", minimum=0, minimum_inclusive=False
        ),
        "risk_aversion": _scenario_number_param(payload, "risk_aversion", minimum=0),
        "max_single_weight": _scenario_number_param(
            payload,
            "max_single_weight",
            minimum=0,
            maximum=1,
            minimum_inclusive=False,
        ),
        "max_high_risk_weight": _scenario_number_param(
            payload, "max_high_risk_weight", minimum=0, maximum=1
        ),
        "min_liquid_weight": _scenario_number_param(
            payload, "min_liquid_weight", minimum=0, maximum=1
        ),
        "min_holdings": min_holdings,
    }


def list_portfolio_scenarios() -> list[dict]:
    try:
        connection = database_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {SCENARIO_COLUMNS} FROM app_portfolio_scenario "
                    "ORDER BY scenario_type DESC, scenario_id"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ScenarioStoreError("unable to list portfolio scenarios") from exc
    return [_scenario_json(row) for row in rows]


def create_portfolio_scenario(payload: dict) -> dict:
    try:
        connection = database_connection()
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        raise ScenarioStoreError("unable to save portfolio scenario") from exc

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS product_count FROM dwd_dim_product")
            product_count = int(cursor.fetchone()["product_count"])
            if product_count == 0:
                raise ScenarioStoreError("product data is empty")

            values = scenario_values(payload, max_holdings=product_count)
            scenario_id = f"CUSTOM_{uuid4().hex[:12].upper()}"
            cursor.execute(
                "INSERT INTO app_portfolio_scenario "
                "(scenario_id, scenario_name, scenario_type, total_amount, "
                "risk_aversion, max_single_weight, max_high_risk_weight, "
                "min_liquid_weight, min_holdings) "
                "VALUES (%s, %s, 'custom', %s, %s, %s, %s, %s, %s)",
                (
                    scenario_id,
                    values["scenario_name"],
                    values["total_amount"],
                    values["risk_aversion"],
                    values["max_single_weight"],
                    values["max_high_risk_weight"],
                    values["min_liquid_weight"],
                    values["min_holdings"],
                ),
            )
            cursor.execute(
                f"SELECT {SCENARIO_COLUMNS} FROM app_portfolio_scenario "
                "WHERE scenario_id = %s",
                (scenario_id,),
            )
            row = cursor.fetchone()
        connection.commit()
    except ScenarioInputError:
        connection.rollback()
        raise
    except ScenarioStoreError:
        connection.rollback()
        raise
    except (pymysql.MySQLError, OSError, ValueError) as exc:
        connection.rollback()
        raise ScenarioStoreError("unable to save portfolio scenario") from exc
    finally:
        connection.close()

    if row is None:
        raise ScenarioStoreError("saved portfolio scenario was not found")
    return _scenario_json(row)


def _ai_prompt(payload: dict) -> str:
    summary = payload.get("summary") or {}
    business = payload.get("business") or {}
    customer = payload.get("customer") or {}
    buys = [f"{item.get('product_name')}(+{item.get('amount', 0):.0f}元)" for item in payload.get("buys") or []]
    sells = [f"{item.get('product_name')}(-{item.get('amount', 0):.0f}元)" for item in payload.get("sells") or []]
    prob = payload.get("marketing_prob")

    return (
        "你是一名银行财富管理投顾助手。请根据以下组合优化结果，用一段话（120字以内，"
        "纯文本、不用markdown、不列条款）向客户经理解读这个方案：先点明客户风险画像，"
        "再说明理论最优方案的收益/波动，然后解释业务落地后的保真率和调仓要点，最后给一句"
        "可执行的跟进建议。\n\n"
        f"客户：风险偏好 {customer.get('risk_appetite')}，AUM {customer.get('aum', 0):.0f} 元。\n"
        f"理论方案：预期收益 {(summary.get('expected_return', 0) * 100):.2f}%，"
        f"波动 {(summary.get('portfolio_volatility', 0) * 100):.2f}%，"
        f"持仓 {summary.get('holdings_count')} 款。\n"
        f"业务落地：保真率 {(business.get('retention_ratio', 0) * 100):.1f}%，"
        f"持仓 {business.get('holdings_count')} 款。\n"
        f"调仓：买入 {('、'.join(buys)) if buys else '无'}；卖出 {('、'.join(sells)) if sells else '无'}。\n"
        + (f"营销：该客户 A1 响应概率 {(prob * 100):.1f}%。\n" if prob is not None else "")
    )


def stream_ai_analysis(payload: dict):
    """流式调用 DeepSeek，逐段 yield 文本增量（供 SSE 端点使用）。"""
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai SDK is not installed") from exc

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _ai_prompt(payload)}],
        temperature=0.4,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def generate_ai_analysis(payload: dict) -> str:
    """调用 DeepSeek 生成一段组合解读（纯文本，供前端 AI 分析展示）。"""
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai SDK is not installed") from exc

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _ai_prompt(payload)}],
        temperature=0.4,
    )
    return (response.choices[0].message.content or "").strip()
