"""A2 正式提交导出：完整 A1 客户×产品评分后执行基础规则。

该入口与 MySQL 营销日批共用 ``compute_marketing_batch``。区别只在数据适配层：
赛事复现读取官方原始 CSV，业务平台读取 DWD；二者使用同一 full 模型产物、
同一特征服务、同一规则目录和同一 Top3 逻辑，不读取 A1/A2 提交结果 CSV。
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from ..partA1serving import estimators as model_catalog
from ..partA1serving.data_source import A1DataSource, CsvDataSource
from ..partA1serving.predictor import ResponsePredictor
from .batch import MarketingBatchResult, compute_marketing_batch
from .io import load_strategy_customers
from .models import DEFAULT_MANAGER_QUOTA, STRATEGY_COLUMNS
from .validate import validate_strategy_file
from .warehouse import load_marketing_context

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_DIR / "src" / "data" / "raw"


def generate_batches(
    strategy_dates: Mapping[str, date],
    *,
    predictor: ResponsePredictor,
    data_source: A1DataSource,
    manager_quota: int = DEFAULT_MANAGER_QUOTA,
) -> list[MarketingBatchResult]:
    """按策略日分组生成批次；每位客户都会覆盖完整产品池。"""
    if not strategy_dates:
        raise ValueError("strategy customer list must not be empty")
    by_date: dict[date, list[str]] = defaultdict(list)
    for customer_id, strategy_date in strategy_dates.items():
        by_date[strategy_date].append(customer_id)

    batches: list[MarketingBatchResult] = []
    for strategy_date in sorted(by_date):
        customer_ids = sorted(by_date[strategy_date])
        context = load_marketing_context(
            strategy_date,
            customer_ids=customer_ids,
            data_source=data_source,
        )
        batches.append(
            compute_marketing_batch(
                context,
                predictor,
                batch_id=(
                    f"submission_{strategy_date:%Y%m%d}_"
                    f"{predictor.profile}_{predictor.model_name}"
                ),
                manager_quota=manager_quota,
            )
        )
    return batches


def write_outputs(
    output_path: Path,
    audit_path: Path,
    batches: Sequence[MarketingBatchResult],
) -> None:
    """写出题面六列与可解释审计文件。"""
    strategy_rows = sorted(
        (row for batch in batches for row in batch.strategy_rows),
        key=lambda row: (row[1], row[2]),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(STRATEGY_COLUMNS)
        for row in strategy_rows:
            writer.writerow([row[1], row[2], row[4], row[5], row[6], row[7]])

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(
            [
                "strategy_date",
                "customer_id",
                "rank",
                "product_id",
                "model_prob",
                "a1_rank",
                "recommended_channel",
                "recommended_time",
                "script_length",
                "model_version",
                "rule_version",
                "batch_id",
                "selection_reason",
                "rule_trace_json",
            ]
        )
        for row in strategy_rows:
            writer.writerow(
                [
                    row[0],
                    row[1],
                    row[2],
                    row[4],
                    f"{float(row[8]):.8f}",
                    row[9],
                    row[5],
                    row[6],
                    len(row[7]),
                    row[12],
                    row[13],
                    row[14],
                    row[11],
                    row[10],
                ]
            )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A2正式导出：full A1完整评分 + 基础规则过滤 + Top3"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--strategy-customers",
        type=Path,
        default=DEFAULT_DATA_DIR / "partA_strategy_customers.csv",
    )
    parser.add_argument(
        "--output", type=Path, default=PROJECT_DIR / "partA_strategy.csv"
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=PROJECT_DIR / "src" / "data" / "outputs" / "a2_strategy_audit.csv",
    )
    parser.add_argument(
        "--model",
        choices=model_catalog.list_models(),
        default="lgbm_onehot",
    )
    parser.add_argument("--manager-quota", type=int, default=DEFAULT_MANAGER_QUOTA)
    args = parser.parse_args(argv)
    if args.manager_quota < 0:
        parser.error("--manager-quota 必须大于等于0")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    strategy_dates = load_strategy_customers(args.strategy_customers)
    data_source = CsvDataSource(args.data_dir)
    predictor = ResponsePredictor(
        profile="full",
        model=args.model,
        data_source=data_source,
    )
    print(
        f"[START] A2 submission customers={len(strategy_dates)} "
        f"model=full/{args.model}",
        flush=True,
    )
    batches = generate_batches(
        strategy_dates,
        predictor=predictor,
        data_source=data_source,
        manager_quota=args.manager_quota,
    )
    write_outputs(args.output, args.audit_output, batches)

    expected_customers = set(strategy_dates)
    errors = validate_strategy_file(
        args.output,
        expected_customers=expected_customers,
    )
    if errors:
        raise ValueError("A2正式文件校验失败：" + "; ".join(errors))

    score_count = sum(len(batch.score_rows) for batch in batches)
    decision_count = sum(len(batch.decision_rows) for batch in batches)
    strategy_count = sum(len(batch.strategy_rows) for batch in batches)
    print(
        f"[OK] customers={len(strategy_dates)} products_per_customer="
        f"{score_count // len(strategy_dates)} a1_scores={score_count} "
        f"a2_decisions={decision_count} top3={strategy_count}",
        flush=True,
    )
    print(f"已写出 {args.output}")
    print(f"审计文件 {args.audit_output}")
    return 0


__all__ = ["generate_batches", "main", "parse_args", "write_outputs"]
