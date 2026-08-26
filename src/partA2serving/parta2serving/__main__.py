"""CLI: train | predict-top3 | predict-matrix | export-matrix-example"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_MODEL_PATH, STRATEGY_ASOF
from .data import load_tables
from .features import build_product_grid, matrix_from_frame, FEATURE_COLUMNS
from .inference import predict_top3, predict_top3_simple
from .predictor import A2ProductRanker
from .training import train_ltr_model


def cmd_train(args: argparse.Namespace) -> None:
    model_path = Path(args.model) if args.model else DEFAULT_MODEL_PATH
    tables = load_tables(Path(args.data_dir) if args.data_dir else None)
    _, meta = train_ltr_model(model_path=model_path, tables=tables)
    meta["as_of"] = args.as_of
    out = Path(args.meta_out) if args.meta_out else model_path.parent / "train_meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def cmd_predict_top3(args: argparse.Namespace) -> None:
    model_path = Path(args.model) if args.model else DEFAULT_MODEL_PATH
    ranker, _ = A2ProductRanker.load_or_train(
        model_path=model_path,
        retrain=args.retrain,
        as_of=args.as_of,
        tables=load_tables(Path(args.data_dir) if args.data_dir else None),
    )
    df = ranker.predict_top3(args.customers, include_scores=args.include_scores)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"wrote {args.out}")
    else:
        print(df.to_string(index=False))


def cmd_predict_matrix(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    model_path = Path(args.model) if args.model else DEFAULT_MODEL_PATH
    if args.simple:
        result = predict_top3_simple(
            payload["features"], payload["product_ids"], model_path=model_path
        )
    else:
        result = predict_top3(
            payload["features"], payload["product_ids"], model_path=model_path
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_export_matrix_example(args: argparse.Namespace) -> None:
    tables = load_tables(Path(args.data_dir) if args.data_dir else None)
    ranker = A2ProductRanker.load(
        Path(args.model) if args.model else DEFAULT_MODEL_PATH,
        as_of=args.as_of,
        tables=tables,
    )
    grid = build_product_grid([args.customer], ranker.ctx)
    X, _ = matrix_from_frame(grid)
    payload = {
        "customer_id": args.customer,
        "product_ids": grid["product_id"].tolist(),
        "feature_columns": FEATURE_COLUMNS,
        "features": X.values.tolist(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Part A2 LTR serving")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_train = sub.add_parser("train", help="训练 LGBMRanker 并保存模型")
    p_train.add_argument("--data-dir", default=None)
    p_train.add_argument("--as-of", default=STRATEGY_ASOF)
    p_train.add_argument("--model", default=None)
    p_train.add_argument("--meta-out", default=None)

    p_top3 = sub.add_parser("predict-top3", help="输入客户 ID，输出 Top3")
    p_top3.add_argument("--customers", nargs="+", required=True)
    p_top3.add_argument("--data-dir", default=None)
    p_top3.add_argument("--as-of", default=STRATEGY_ASOF)
    p_top3.add_argument("--model", default=None)
    p_top3.add_argument("--retrain", action="store_true")
    p_top3.add_argument("--include-scores", action="store_true")
    p_top3.add_argument("--out", default=None)

    p_mat = sub.add_parser("predict-matrix", help="30×52 JSON 输入 → Top3")
    p_mat.add_argument("--input", required=True)
    p_mat.add_argument("--model", default=None)
    p_mat.add_argument("--simple", action="store_true")

    p_ex = sub.add_parser("export-matrix-example", help="导出单客户 30×52 示例 JSON")
    p_ex.add_argument("--customer", default="C000010")
    p_ex.add_argument("--data-dir", default=None)
    p_ex.add_argument("--as-of", default=STRATEGY_ASOF)
    p_ex.add_argument("--model", default=None)
    p_ex.add_argument("--out", default="examples/matrix_C000010.json")

    args = parser.parse_args(argv)
    handlers = {
        "train": cmd_train,
        "predict-top3": cmd_predict_top3,
        "predict-matrix": cmd_predict_matrix,
        "export-matrix-example": cmd_export_matrix_example,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
