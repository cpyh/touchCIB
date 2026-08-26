#!/usr/bin/env python3
"""一键复现编排（demo 动作⑤）：进数 → 质量门禁 → A1 → A2 → Part B → 红线校验。

    python -m src.pipelines.run_all                # 全链路（A1 用队友LGBM模型）
    python -m src.pipelines.run_all --model src/data/outputs/a1_final.joblib
                                                   # A1 用最终 LGBM artifact
    python -m src.pipelines.run_all --with-demo    # 追加：日批缓存重建 + 演示事件预置

任何一步失败立即中止并报告阶段名；全部通过则打印"全链路复现成功"。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]

STAGES: list[tuple[str, str, list[str]]] = [
    (
        "进数建表",
        "src.scripts.init_db",
        [],
    ),
    (
        "质量门禁",
        "unittest",
        ["discover", "-s", "src/tests", "-q"],
    ),
    (
        "A2 策略生成",
        "src.marketing.pipeline",
        [],
    ),
    (
        "Part B 组合优化",
        "src.pipelines.solve_partB",
        [
            "--data-dir", "src/data/raw",
            "--audit", "src/data/outputs/partB_optimality_audit.csv",
        ],
    ),
    (
        "三 CSV 红线校验",
        "src.scripts.check_submission",
        [],
    ),
]


def run_stage(name: str, module: str, args: list[str]) -> None:
    run_command(name, [sys.executable, "-m", module, *args])


def run_command(name: str, command: list[str]) -> None:
    print(f"\n===== {name} =====", flush=True)
    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(completed.stdout)
    if completed.stderr.strip():
        sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"[FAIL] 阶段「{name}」退出码 {completed.returncode}")
    print(f"[OK] {name}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="兼容旧A1模型artifact；缺省走partA1serving新模型",
    )
    parser.add_argument(
        "--a1-model",
        choices=("lr", "lgbm", "lgbm_onehot"),
        default="lgbm_onehot",
        help="partA1serving模型类型（默认lgbm_onehot）",
    )
    parser.add_argument(
        "--manager-quota",
        type=int,
        default=None,
        help="A2 manager 配额（缺省用 pipeline 默认值）",
    )
    parser.add_argument(
        "--with-demo",
        action="store_true",
        help="追加演示准备：重建日批缓存 + 重置并预置演示事件（22/30）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 阶段 1-2：进数 + 质量门禁（顺序固定）
    for name, module, stage_args in STAGES[:2]:
        run_stage(name, module, stage_args)

    # 阶段 3：A1 训练/推理
    if args.model is not None:
        run_stage(
            "A1 推理（提交模型）",
            "src.a1_inference",
            ["--model", str(args.model), "--source", "mysql", "--persist-db"],
        )
    else:
        run_stage(
            f"A1训练与推理（{args.a1_model}）",
            "src.partA1serving.training.predict",
            ["--model", args.a1_model, "--out", "partA_prediction.csv"],
        )

    # 阶段 4-6：A2 / Part B / 红线校验
    a2_args: list[str] = []
    if args.manager_quota is not None:
        a2_args += ["--manager-quota", str(args.manager_quota)]
    for name, module, stage_args in STAGES[2:]:
        if name.startswith("A2"):
            stage_args = a2_args
            # 包 __init__ 已导入 pipeline，避免 runpy 双重加载 warning：
            # 直接以 -c 形式调用 main()。
            command = [
                "-c",
                "import sys; from src.marketing.pipeline import main; "
                "sys.exit(main(sys.argv[1:]))",
                *stage_args,
            ]
            run_command(name, command)
            continue
        run_stage(name, module, stage_args)

    # 阶段 7：演示准备（可选）
    if args.with_demo:
        run_stage("日批缓存重建", "src.scripts.build_daily_roster", [])
        run_stage(
            "演示事件预置",
            "src.scripts.seed_demo_events",
            ["--reset"],
        )

    print("\n全链路复现成功：进数 → 质量门禁 → A1 → A2 → Part B → 红线校验。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
