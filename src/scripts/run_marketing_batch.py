#!/usr/bin/env python3
"""运行可重复、幂等的营销评分批处理并写入ADS。

默认处理DWD中的全部客户；开发验证可用 ``--customer-id`` 或 ``--limit``。
同一日期同一客户重复运行时，三张ADS结果在单事务中被替换，不会叠加。
"""

from __future__ import annotations

import argparse
from datetime import date

from src.database import database_connection
from src.marketing.batch import compute_marketing_batch, persist_marketing_batch
from src.marketing.models import DEFAULT_MANAGER_QUOTA
from src.marketing.warehouse import load_marketing_context
from src.partA1serving.runtime import get_mysql_predictor
from src.scripts.init_db import database_name, initialize_schema, load_environment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A1排序+A2规则过滤营销日批")
    parser.add_argument("--strategy-date", default="2026-04-15")
    parser.add_argument("--customer-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-id")
    parser.add_argument(
        "--manager-quota",
        type=int,
        default=DEFAULT_MANAGER_QUOTA,
        help="兼容参数；manager 已不限资格和配额，该值不再生效",
    )
    args = parser.parse_args()
    try:
        args.strategy_date = date.fromisoformat(args.strategy_date)
    except ValueError as exc:
        parser.error(f"--strategy-date 必须是 YYYY-MM-DD：{exc}")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须大于0")
    if args.customer_id and args.limit is not None:
        parser.error("--customer-id 与 --limit 不能同时使用")
    return args


def _customer_scope(args: argparse.Namespace) -> list[str] | None:
    if args.customer_id:
        return [value.strip().upper() for value in args.customer_id if value.strip()]
    if args.limit is None:
        return None
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT customer_id FROM dwd_dim_customer "
                "ORDER BY customer_id LIMIT %s",
                (args.limit,),
            )
            return [str(row["customer_id"]) for row in cursor.fetchall()]
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    load_environment()
    initialize_schema(database_name())
    customer_ids = _customer_scope(args)
    predictor = get_mysql_predictor()
    batch_id = args.batch_id or (
        f"marketing_{args.strategy_date:%Y%m%d}_{predictor.profile}_{predictor.model_name}"
    )
    context = load_marketing_context(
        args.strategy_date,
        customer_ids=customer_ids,
    )
    print(
        f"[START] batch_id={batch_id} date={args.strategy_date} "
        f"customers={len(context.customers)} products={len(context.products)}",
        flush=True,
    )
    result = compute_marketing_batch(
        context,
        predictor,
        batch_id=batch_id,
        manager_quota=args.manager_quota,
    )
    persist_marketing_batch(result)
    print(
        f"[OK] customers={result.customer_count} "
        f"a1_scores={len(result.score_rows)} "
        f"a2_decisions={len(result.decision_rows)} "
        f"top3={len(result.strategy_rows)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
