#!/usr/bin/env python3
"""运行20个预置组合场景批处理并幂等写入ADS。"""

from __future__ import annotations

import argparse
from datetime import date

from src.portfolio import list_portfolio_scenarios
from src.portfolio_batch import compute_portfolio_batch, persist_portfolio_batch
from src.scripts.init_db import database_name, initialize_schema, load_environment


def main() -> int:
    parser = argparse.ArgumentParser(description="组合优化ADS批处理")
    parser.add_argument("--calculation-date", default="2026-04-15")
    parser.add_argument("--batch-id")
    parser.add_argument("--include-custom", action="store_true")
    args = parser.parse_args()
    calculation_date = date.fromisoformat(args.calculation_date)
    load_environment()
    initialize_schema(database_name())
    scenarios = list_portfolio_scenarios()
    if not args.include_custom:
        scenarios = [row for row in scenarios if row["scenario_type"] == "preset"]
    batch_id = args.batch_id or f"portfolio_{calculation_date:%Y%m%d}_v1"
    print(
        f"[START] batch_id={batch_id} date={calculation_date} "
        f"scenarios={len(scenarios)}",
        flush=True,
    )
    result = compute_portfolio_batch(
        calculation_date,
        scenarios,
        batch_id=batch_id,
    )
    persist_portfolio_batch(result)
    print(
        f"[OK] scenarios={len(result.result_rows)} "
        f"allocations={len(result.allocation_rows)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
