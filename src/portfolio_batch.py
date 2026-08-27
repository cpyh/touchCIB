"""组合优化批处理：从MySQL场景表读取参数，计算后幂等写入ADS。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from .database import database_connection
from .portfolio import optimize_portfolio


@dataclass(frozen=True)
class PortfolioBatchResult:
    calculation_date: date
    batch_id: str
    result_rows: tuple[tuple, ...]
    allocation_rows: tuple[tuple, ...]


def compute_portfolio_batch(
    calculation_date: date,
    scenarios: list[dict],
    *,
    batch_id: str,
    optimizer: Callable[[dict], dict] = optimize_portfolio,
) -> PortfolioBatchResult:
    result_rows: list[tuple] = []
    allocation_rows: list[tuple] = []
    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        payload = {
            key: scenario[key]
            for key in (
                "total_amount",
                "risk_aversion",
                "max_single_weight",
                "max_high_risk_weight",
                "min_liquid_weight",
                "min_holdings",
            )
        }
        output = optimizer(payload)
        summary = output["summary"]
        allocations = output["allocations"]
        constraints_satisfied = (
            float(summary["invested_weight"]) <= 1 + 1e-6
            and float(summary["high_risk_weight"])
            <= float(payload["max_high_risk_weight"]) + 1e-6
            and float(summary["liquid_plus_cash"]) + 1e-6
            >= float(payload["min_liquid_weight"])
            and int(summary["holdings_count"]) >= int(payload["min_holdings"])
            and max((float(item["weight"]) for item in allocations), default=0.0)
            <= float(payload["max_single_weight"]) + 1e-6
        )
        result_rows.append(
            (
                calculation_date,
                scenario_id,
                float(payload["total_amount"]),
                float(summary["expected_return"]),
                float(summary["portfolio_volatility"]),
                float(summary["utility"]),
                float(summary["cash_weight"]),
                int(summary["holdings_count"]),
                float(summary["high_risk_weight"]),
                float(summary["liquid_plus_cash"]),
                summary.get("optimality_gap"),
                int(constraints_satisfied),
                batch_id,
            )
        )
        allocation_rows.extend(
            (
                calculation_date,
                scenario_id,
                item["product_id"],
                float(item["weight"]),
                float(item["amount"]),
                batch_id,
            )
            for item in allocations
        )
    return PortfolioBatchResult(
        calculation_date=calculation_date,
        batch_id=batch_id,
        result_rows=tuple(result_rows),
        allocation_rows=tuple(allocation_rows),
    )


def persist_portfolio_batch(
    result: PortfolioBatchResult,
    *,
    connection_factory: Callable = database_connection,
) -> None:
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM ads_portfolio_allocation WHERE calculation_date=%s",
                (result.calculation_date,),
            )
            cursor.execute(
                "DELETE FROM ads_portfolio_result WHERE calculation_date=%s",
                (result.calculation_date,),
            )
            cursor.executemany(
                "INSERT INTO ads_portfolio_result "
                "(calculation_date, scenario_id, total_amount, expected_return, "
                "portfolio_volatility, utility, cash_weight, holdings_count, "
                "high_risk_weight, liquid_plus_cash, optimality_gap, "
                "constraints_satisfied, batch_id) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                result.result_rows,
            )
            cursor.executemany(
                "INSERT INTO ads_portfolio_allocation "
                "(calculation_date, scenario_id, product_id, weight, "
                "allocation_amount, batch_id) VALUES (%s,%s,%s,%s,%s,%s)",
                result.allocation_rows,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "PortfolioBatchResult",
    "compute_portfolio_batch",
    "persist_portfolio_batch",
]
