"""营销响应预测服务的命令行入口。

三种用法
--------
1) 单条打分（已有客户）
   python -m partA1serving.cli \
       --customer-id C000001 --product-id P002 --channel manager

2) 产品推荐 / 渠道优选（运营工作台的典型用法）
   python -m partA1serving.cli --customer-id C000001 --rank-products --top 5
   python -m partA1serving.cli --customer-id C000001 --product-id P002 --best-channel

3) 新客进件（库中无此人，画像由调用方给出）
   python -m partA1serving.cli --product-id P002 --channel manager \
       --new-customer '{"age_group":"35-44","city":"上海","occupation":"企业职员",
                        "income_level":"30-50万","register_date":"2024-01-15",
                        "aum":800000,"risk_appetite":"R3","vip_level":"金卡","has_app":1}'

批量打分（JSON 数组文件，每个元素是一个请求）
   python -m partA1serving.cli --batch requests.json --out scores.json

加 --json 可输出结构化结果，便于被其他程序管道调用。

（以上命令需在 submission/src 加入 sys.path 的前提下运行，如
  cd submission/src 后直接执行，或设置 PYTHONPATH=submission/src）
"""

from __future__ import annotations

import argparse
import json
import sys

from . import model_store
from .feature_service import FeatureAssemblyError, PredictRequest
from .predictor import PredictResult, ResponsePredictor


def _print_result(r: PredictResult, title: str = "") -> None:
    if title:
        print(f"\n{title}")
    print(f"  响应概率   : {r.probability:.6f}")
    print(f"  决策建议   : {r.decision}  {r.decision_label}")
    print(f"  相对基准   : {r.lift_vs_base:.2f} 倍（基准为全体平均响应率）")
    print(f"  模式/基准日 : {r.mode} / {r.as_of}")
    print(f"  模型         : {r.model_name} / profile={r.profile}")
    if r.reasons:
        print("  主要影响因素：")
        for line in r.reasons:
            print(f"    · {line}")
    for w in r.warnings:
        print(f"  ⚠ {w}")


def _print_table(results: list[PredictResult], key_label: str, keys: list[str]) -> None:
    print(f"\n  {'排名':<4}{key_label:<12}{'概率':<12}{'决策':<8}说明")
    for i, (k, r) in enumerate(zip(keys, results, strict=True), start=1):
        print(f"  {i:<4}{k:<12}{r.probability:<12.6f}{r.decision:<8}{r.decision_label}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="营销响应预测服务 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--customer-id", help="已有客户 ID")
    ap.add_argument("--product-id", help="拟推荐产品 ID（P001~P030）")
    ap.add_argument("--channel", help="触达渠道 sms/call/app_push/manager")
    ap.add_argument("--contact-date", help="as-of 基准日，默认取模型训练期最晚日期")
    ap.add_argument("--new-customer", help="新客画像 JSON 字符串")
    ap.add_argument("--rank-products", action="store_true", help="对全部产品打分排序")
    ap.add_argument("--best-channel", action="store_true", help="比较四个渠道")
    ap.add_argument("--top", type=int, default=5, help="排序结果条数，默认 5")
    ap.add_argument("--batch", help="批量请求 JSON 文件路径")
    ap.add_argument("--out", help="批量结果输出路径")
    ap.add_argument(
        "--profile",
        choices=model_store.PROFILES,
        default=model_store.DEFAULT_PROFILE,
        help="demo=训练截止2026-01-31（演示用，默认）；full=全量训练（提交口径）",
    )
    ap.add_argument(
        "--model",
        default="lr",
        help="模型类型：lr / lgbm / lgbm_onehot（需已训练对应产物）",
    )
    ap.add_argument("--models-root", help="模型根目录，默认包内 artifacts/")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(argv)

    try:
        predictor = ResponsePredictor(args.profile, args.model, args.models_root)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    try:
        # ---------------- 批量
        if args.batch:
            with open(args.batch, encoding="utf-8") as fh:
                payloads = json.load(fh)
            if not isinstance(payloads, list):
                print("错误：批量文件应为 JSON 数组", file=sys.stderr)
                return 2
            out = [predictor.predict_dict(p) for p in payloads]
            text = json.dumps(out, ensure_ascii=False, indent=2)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text)
                print(f"已写出 {len(out)} 条结果 -> {args.out}")
            else:
                print(text)
            return 0

        # ---------------- 产品排序
        if args.rank_products:
            if not args.customer_id:
                print("错误：--rank-products 需配合 --customer-id", file=sys.stderr)
                return 2
            channel = args.channel or "manager"
            results = predictor.rank_products(
                args.customer_id, channel, args.contact_date, args.top
            )
            if args.json:
                print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
            else:
                print(f"\n客户 {args.customer_id} 走 {channel} 渠道的产品推荐（Top {args.top}）")
                _print_table(results, "产品", [r.product_id for r in results])
            return 0

        # ---------------- 渠道优选
        if args.best_channel:
            if not (args.customer_id and args.product_id):
                print("错误：--best-channel 需配合 --customer-id 与 --product-id", file=sys.stderr)
                return 2
            results = predictor.best_channel(args.customer_id, args.product_id, args.contact_date)
            if args.json:
                print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
            else:
                print(f"\n客户 {args.customer_id} 推 {args.product_id} 的渠道对比")
                _print_table(results, "渠道", [r.channel for r in results])
            return 0

        # ---------------- 单条
        if not (args.product_id and args.channel):
            ap.print_help()
            return 2
        customer = json.loads(args.new_customer) if args.new_customer else {}
        req = PredictRequest(
            product_id=args.product_id,
            channel=args.channel,
            customer_id=args.customer_id,
            contact_date=args.contact_date,
            customer=customer,
        )
        result = predictor.predict(req)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            who = args.customer_id or "（新客）"
            _print_result(result, f"客户 {who} × 产品 {args.product_id} × 渠道 {args.channel}")
        return 0

    except FeatureAssemblyError as exc:
        print(f"入参错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
