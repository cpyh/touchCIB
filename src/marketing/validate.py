"""A2 提交格式校验器（与题目红线逐条对应，队友提交前可独立调用）。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping, Sequence

from .models import CHANNELS, STRATEGY_COLUMNS, TIME_SLOTS

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB


def validate_strategy_rows(
    rows: Sequence[Mapping[str, str]]
) -> list[str]:
    """校验策略行列表，返回错误信息列表（空 = 全部通过）。"""
    errors: list[str] = []
    per_customer: dict[str, list[Mapping[str, str]]] = {}
    for index, row in enumerate(rows, start=2):
        customer_id = str(row.get("customer_id", "")).strip()
        if not customer_id:
            errors.append(f"第 {index} 行：customer_id 为空")
            continue

        rank_raw = str(row.get("rank", "")).strip()
        if rank_raw not in {"1", "2", "3"}:
            errors.append(f"{customer_id} 第 {index} 行：rank={rank_raw!r}，须为 1/2/3")
        else:
            per_customer.setdefault(customer_id, []).append(row)

        product_id = str(row.get("product_id", "")).strip()
        if not product_id:
            errors.append(f"{customer_id} 第 {index} 行：product_id 为空")

        channel = str(row.get("recommended_channel", "")).strip()
        if channel not in CHANNELS:
            errors.append(
                f"{customer_id} 第 {index} 行：recommended_channel={channel!r}"
                f" 不在 {CHANNELS}"
            )

        slot = str(row.get("recommended_time", "")).strip()
        if slot not in TIME_SLOTS:
            errors.append(
                f"{customer_id} 第 {index} 行：recommended_time={slot!r}"
                " 不在题目规定枚举"
            )

        script = str(row.get("marketing_script", ""))
        if not 10 <= len(script) <= 300:
            errors.append(
                f"{customer_id} 第 {index} 行：marketing_script 长度"
                f" {len(script)} 不在 [10, 300]"
            )

    for customer_id, customer_rows in per_customer.items():
        if len(customer_rows) != 3:
            errors.append(
                f"{customer_id}：行数 {len(customer_rows)}，须恰好 3 行"
            )
            continue
        ranks = [row["rank"].strip() for row in customer_rows]
        if set(ranks) != {"1", "2", "3"}:
            errors.append(f"{customer_id}：rank 集合为 {sorted(set(ranks))}，须为 1/2/3 各一")
        products = [row["product_id"].strip() for row in customer_rows]
        if len(set(products)) != 3:
            errors.append(f"{customer_id}：3 个 product_id 存在重复")

    return errors


def validate_strategy_file(
    path: Path,
    *,
    expected_customers: set[str] | None = None,
) -> list[str]:
    """校验 partA_strategy.csv 文件，返回错误列表（空 = 可通过格式检查）。"""
    errors: list[str] = []
    try:
        size = path.stat().st_size
    except OSError:
        return [f"文件不可读：{path}"]
    if size > MAX_FILE_SIZE:
        errors.append(f"文件大小 {size} 字节超过 10 MiB 限制")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if list(reader.fieldnames or []) != list(STRATEGY_COLUMNS):
            errors.append(
                f"列名不符：期望 {list(STRATEGY_COLUMNS)}，实际 {reader.fieldnames}"
            )
            return errors
        rows = list(reader)

    errors.extend(validate_strategy_rows(rows))

    if expected_customers is not None:
        actual = {row["customer_id"].strip() for row in rows}
        if actual != expected_customers:
            missing = expected_customers - actual
            extra = actual - expected_customers
            if missing:
                errors.append(f"缺少客户（{len(missing)}）：{sorted(missing)[:5]}...")
            if extra:
                errors.append(f"多出客户（{len(extra)}）：{sorted(extra)[:5]}...")
    return errors
