"""预置演示事件：30 条 manager 渠道策略已触达，其中 22 条已响应。

设计（docs/demo-design.md §4.3）：
- KPI 开场即"经理 MGR001 4月转化 22/30 ≈ 73%"，
  演示动作"标记 responded"→ 23/30，进度条 +1；
- 漏斗一致性：策略覆盖全量客户 → 已触达 30 → 已响应 22；
- 全部事件走 src.campaign 服务函数（归因校验 + append-only），
  与前端埋点按钮同一代码路径。

用法：
    python -m src.scripts.seed_demo_events            # 幂等：已存在则跳过
    python -m src.scripts.seed_demo_events --reset    # 清空事件表后重播
    python -m src.scripts.seed_demo_events --sent 40 --responded 30
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta

import pandas as pd

from src.campaign import (
    create_responded_event,
    create_sent_event,
    load_strategy_frame,
)
from src.database import database_connection

SEED_SENT = 30
SEED_RESPONDED = 22
FIRST_SENT_AT = datetime(2026, 4, 15, 9, 0, 0)
FIRST_BUY_DATE = date(2026, 4, 16)


def _existing_events(strategy_ids: list[str]) -> dict[str, set[str]]:
    """strategy_id -> 已存在的事件类型集合。"""
    if not strategy_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(strategy_ids))
    statement = (
        "SELECT strategy_id, event_type FROM app_campaign_event "
        f"WHERE strategy_id IN ({placeholders})"
    )
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement, tuple(strategy_ids))
            rows = cursor.fetchall()
    finally:
        connection.close()
    result: dict[str, set[str]] = {}
    for row in rows:
        result.setdefault(row["strategy_id"], set()).add(row["event_type"])
    return result


def _pick_targets(sent: int) -> pd.DataFrame:
    """确定性挑选：rank=1 且 channel=manager 的前 N 个客户。"""
    frame = load_strategy_frame()
    rank1 = frame[(frame["rank"] == "1") & (frame["recommended_channel"] == "manager")]
    if len(rank1) < sent:
        raise SystemExit(
            f"manager 渠道 rank=1 策略仅 {len(rank1)} 行，不足 {sent} 条"
        )
    return rank1.sort_values("customer_id").head(sent).reset_index(drop=True)


def _clear_events() -> None:
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM app_campaign_event")
        connection.commit()
    finally:
        connection.close()
    print("已清空 app_campaign_event（--reset）")


def seed(sent: int, responded: int, reset: bool = False) -> dict:
    if responded > sent:
        raise SystemExit("--responded 不能大于 --sent")
    if reset:
        _clear_events()

    targets = _pick_targets(sent)
    strategy_ids = [f"{row.customer_id}:1" for row in targets.itertuples()]
    existing = _existing_events(strategy_ids)

    sent_count = responded_count = skipped = 0
    for index, row in targets.iterrows():
        strategy_id = f"{row.customer_id}:1"
        types = existing.get(strategy_id, set())

        if "sent" not in types:
            create_sent_event(
                strategy_id,
                occurred_at=FIRST_SENT_AT + timedelta(minutes=index),
            )
            sent_count += 1
        else:
            skipped += 1

        if index < responded:
            if "responded" in types:
                skipped += 1
                continue
            buy_date = FIRST_BUY_DATE + timedelta(days=index % 10)
            create_responded_event(
                customer_id=row.customer_id,
                product_id=row.product_id,
                buy_date=buy_date,
                amount=float(50000 + index * 5000),
                occurred_at=datetime.combine(buy_date, time(10, 30)),
            )
            responded_count += 1

    summary = {
        "sent_written": sent_count,
        "responded_written": responded_count,
        "skipped": skipped,
        "manager_conversion": f"{responded}/{sent} = {responded / sent:.1%}",
        "manager_response_rate": f"{responded}/{sent} = {responded / sent:.1%}",
        "demo_hint": (
            "演示动作：Tab3 对第 23 个客户标记已响应 → "
            f"经理转化 KPI {responded}/{sent} → {responded + 1}/{sent}"
        ),
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sent", type=int, default=SEED_SENT)
    parser.add_argument("--responded", type=int, default=SEED_RESPONDED)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)

    summary = seed(args.sent, args.responded, reset=args.reset)
    print("预置演示事件完成：")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
