"""部署引导：解除路径硬绑定 + 启动自检。

为什么需要
----------
`config.py` 默认按目录层级推导数据与模型路径（数据默认指向 `<pkg>/data`，
模型默认指向包内 `artifacts/`）。仓库内开箱即用，但外部系统集成时数据目录
往往不同，一旦挪动位置，路径会**静默**指向错误位置——典型表现是
`FileNotFoundError: /private/tmp/data/...`，报错路径看着莫名其妙，
排查成本很高。

本模块提供两件事：

1. ``configure()`` —— 用显式参数或环境变量覆盖路径。
   必须在构造 ``ResponsePredictor`` / ``FeatureService`` 之前调用。

2. ``verify()`` —— 启动自检，**一次性列出全部缺失项**。
   这比"运行到哪崩到哪"重要：服务启动阶段就该暴露部署问题，
   而不是等第一个线上请求打进来才发现少了一张表。

只依赖标准库，不触发 pandas / sklearn 导入，因此自检开销极小（毫秒级），
可放在容器 readiness probe 里。

配置优先级
----------
    显式参数  >  环境变量  >  默认目录层级推导

环境变量清单
------------
    WMP_PKG_DIR                 数据包根目录（data/ 的上级）
    WMP_DATA_DIR                直接指定 data/ 目录，优先于 WMP_PKG_DIR 推导
    WMP_MODELS_DIR              模型根目录（默认随包内置的 artifacts/）
    WMP_TEST_CONTACTS_CSV       partA_test_contacts.csv（仅离线打分需要）
    WMP_STRATEGY_CUSTOMERS_CSV  partA_strategy_customers.csv（仅 A2 需要）

典型用法（外部后端集成）
------------------------
    from partA1serving import bootstrap

    bootstrap.configure(data_dir="/srv/wmp/data", models_dir="/srv/wmp/models")

    report = bootstrap.verify(profile="full", model="lgbm_onehot")
    if not report.ok:
        raise SystemExit(report.render())

    from partA1serving import ResponsePredictor     # 配置生效后再构造
    predictor = ResponsePredictor(profile="full", model="lgbm_onehot")

命令行自检
----------
    python -m partA1serving.bootstrap --profile full --model lgbm_onehot
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field

from . import config

# 在线推理必需的模型产物文件名模板（与 model_store 保持一致，此处不导入它，
# 以维持"仅标准库"的特性——model_store 会拉入 joblib）
_MODEL_FILE = "a1_response_{model}.joblib"
_META_FILE = "a1_response_{model}.meta.json"


# ---------------------------------------------------------------- 配置


def configure(
    pkg_dir: str | None = None,
    data_dir: str | None = None,
    models_dir: str | None = None,
    test_contacts_csv: str | None = None,
    strategy_customers_csv: str | None = None,
) -> dict[str, str]:
    """覆盖路径配置，返回生效后的路径快照。

    未显式给出的项按 环境变量 > 默认推导 解析，因此可以只覆盖其中一两项。

    调用时机很关键：``FeatureService`` 在构造时就把参考数据读进内存，
    之后再改路径不会重新加载。故必须在构造预测器之前调用。
    """
    config.configure_paths(
        pkg_dir=pkg_dir,
        data_dir=data_dir,
        models_dir=models_dir,
        test_contacts_csv=test_contacts_csv,
        strategy_customers_csv=strategy_customers_csv,
    )
    return config.current_paths()


def configure_from_env() -> dict[str, str]:
    """仅按环境变量重新解析。等价于 ``configure()`` 不带参数。"""
    return configure()


def describe() -> dict[str, str]:
    """当前生效的路径快照。"""
    return config.current_paths()


# ---------------------------------------------------------------- 自检


@dataclass
class CheckItem:
    """单项检查结果。"""

    name: str
    path: str
    exists: bool
    required: bool
    note: str = ""

    @property
    def status(self) -> str:
        if self.exists:
            return "OK"
        return "MISSING" if self.required else "SKIP"


@dataclass
class VerifyReport:
    """自检报告。``ok`` 为 False 时不应继续启动服务。"""

    items: list[CheckItem] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(i.exists for i in self.items if i.required)

    @property
    def missing(self) -> list[CheckItem]:
        return [i for i in self.items if i.required and not i.exists]

    def render(self) -> str:
        """人类可读报告。失败时附带最可能的原因，避免只丢一个路径让人猜。"""
        lines = ["", "=" * 66, "营销响应预测服务 —— 部署自检", "=" * 66, "", "[生效路径]"]
        lines += [f"  {k:<22}: {v}" for k, v in self.paths.items()]

        lines += ["", "[检查项]"]
        for i in self.items:
            mark = {"OK": "  ok  ", "MISSING": " MISS ", "SKIP": " skip "}[i.status]
            suffix = f"  <- {i.note}" if i.note else ""
            lines.append(f"  [{mark}] {i.name:<26} {i.path}{suffix}")

        if self.ok:
            lines += ["", "自检通过，可以启动服务。", ""]
        else:
            lines += ["", f"自检未通过，缺少 {len(self.missing)} 项必需文件：", ""]
            lines += [f"  - {i.name}: {i.path}" for i in self.missing]
            lines += [
                "",
                "常见原因：",
                "  1. 数据目录未配置或目录层级不再是 <pkg>/data；",
                "     -> 用 bootstrap.configure(data_dir=..., models_dir=...) 显式指定，",
                f"        或设置环境变量 {config.ENV_DATA_DIR} / {config.ENV_MODELS_DIR}",
                "  2. 模型产物未训练；",
                "     -> python -m partA1serving.training.train_and_save "
                "--profile full --model lgbm_onehot",
                "",
            ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "paths": self.paths,
            "items": [
                {
                    "name": i.name,
                    "path": i.path,
                    "exists": i.exists,
                    "required": i.required,
                    "status": i.status,
                }
                for i in self.items
            ],
        }


def verify(
    profile: str = "full",
    model: str = "lgbm_onehot",
    require_test_contacts: bool = False,
    require_strategy_customers: bool = False,
) -> VerifyReport:
    """检查在线服务所需的全部文件是否就位。

    Args:
        profile: 待检查的模型 profile（demo / full）。
        model: 待检查的模型类型（lr / lgbm_onehot / ...）。
        require_test_contacts: 是否要求 partA_test_contacts.csv。
            在线服务用不到它（那是离线批量打分的输入），默认不要求。
        require_strategy_customers: 是否要求 partA_strategy_customers.csv（A2 用）。

    Returns:
        VerifyReport。``ok`` 为 True 表示可以安全启动。
    """
    items: list[CheckItem] = []

    items.append(
        CheckItem("data 目录", config.DATA_DIR, os.path.isdir(config.DATA_DIR), True)
    )
    for fname in config.SERVING_DATA_FILES:
        p = os.path.join(config.DATA_DIR, fname)
        items.append(CheckItem(f"参考数据/{fname}", p, os.path.isfile(p), True))

    model_dir = os.path.join(config.MODELS_DIR, profile)
    items.append(CheckItem(f"模型目录/{profile}", model_dir, os.path.isdir(model_dir), True))

    mp = os.path.join(model_dir, _MODEL_FILE.format(model=model))
    meta = os.path.join(model_dir, _META_FILE.format(model=model))
    items.append(CheckItem(f"模型/{model}", mp, os.path.isfile(mp), True))
    items.append(CheckItem(f"元数据/{model}", meta, os.path.isfile(meta), True))

    items.append(
        CheckItem(
            "partA_test_contacts.csv",
            config.TEST_CONTACTS_CSV,
            os.path.isfile(config.TEST_CONTACTS_CSV),
            require_test_contacts,
            "" if require_test_contacts else "在线服务不需要，仅离线打分用",
        )
    )
    items.append(
        CheckItem(
            "partA_strategy_customers.csv",
            config.STRATEGY_CUSTOMERS_CSV,
            os.path.isfile(config.STRATEGY_CUSTOMERS_CSV),
            require_strategy_customers,
            "" if require_strategy_customers else "在线服务不需要，仅 A2 用",
        )
    )

    return VerifyReport(items=items, paths=config.current_paths())


def ensure(profile: str = "full", model: str = "lgbm_onehot") -> None:
    """自检不通过就抛异常。适合放在服务启动流程里。"""
    report = verify(profile=profile, model=model)
    if not report.ok:
        raise RuntimeError(report.render())


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="营销响应预测服务部署自检",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m partA1serving.bootstrap\n"
            "  python -m partA1serving.bootstrap --profile demo --model lr\n"
            "  WMP_DATA_DIR=/srv/wmp/data python -m partA1serving.bootstrap\n"
        ),
    )
    ap.add_argument("--profile", default="full", help="模型 profile，默认 full")
    ap.add_argument("--model", default="lgbm_onehot", help="模型类型，默认 lgbm_onehot")
    ap.add_argument("--data-dir", help="覆盖 data 目录")
    ap.add_argument("--models-dir", help="覆盖模型根目录")
    ap.add_argument("--pkg-dir", help="覆盖数据包根目录")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出，便于脚本消费")
    args = ap.parse_args(argv)

    configure(pkg_dir=args.pkg_dir, data_dir=args.data_dir, models_dir=args.models_dir)
    report = verify(profile=args.profile, model=args.model)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
