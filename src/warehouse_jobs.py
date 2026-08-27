"""受控的数据任务编排器：供演示页面手动触发业务数仓日批。"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .database import database_connection
from .business_date import DEFAULT_BUSINESS_DATE


PROJECT_DIR = Path(__file__).resolve().parents[1]
DWS_SNAPSHOT_DATE = date(2026, 3, 31)
RunStatus = Literal["pending", "running", "success", "failed", "skipped"]


class PipelineBusyError(RuntimeError):
    """已有流水线正在执行。"""


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    name: str
    layer: str
    description: str
    output: str
    depends_on: tuple[str, ...]
    module: str | None
    args: tuple[str, ...] = ()


STAGES = (
    StageDefinition(
        "warehouse",
        "数仓分层刷新",
        "ODS · DWD · DWS",
        "导入贴源数据，重建标准明细与客户画像快照",
        "5张ODS · 5张DWD · dws_customer_360",
        (),
        "src.scripts.init_db",
    ),
    StageDefinition(
        "quality",
        "数据质量门禁",
        "DATA QUALITY",
        "检查完整性、域值、关系、时序和快照口径",
        "41项质量规则",
        ("warehouse",),
        "src.scripts.check_data_quality",
    ),
    StageDefinition(
        "marketing",
        "营销策略日批",
        "A1 · A2 · ADS",
        "A1全量评分，A2规则过滤并固化客户Top3",
        "评分、候选决策、营销策略ADS",
        ("quality",),
        "src.scripts.run_marketing_batch",
    ),
    StageDefinition(
        "portfolio",
        "组合优化日批",
        "PART B · ADS",
        "执行20个预设场景并幂等写入组合结果",
        "组合结果与产品配置明细ADS",
        ("quality",),
        "src.scripts.run_portfolio_batch",
    ),
    StageDefinition(
        "bi",
        "BI数据就绪",
        "BI SERVING",
        "核对DWS与所选业务日期的ADS批次，供经营看板查询",
        "可视化看板批次指标",
        ("marketing", "portfolio"),
        None,
    ),
)

_lock = threading.RLock()
_latest_run: dict | None = None
_active_thread: threading.Thread | None = None
_MAX_LOG_LINES = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pipeline_definition() -> dict:
    return {
        "pipeline_id": "wealth_warehouse_daily",
        "name": "智能财富管理业务日批",
        "schedule": "演示模式 · 手动触发",
        "default_business_date": DEFAULT_BUSINESS_DATE.isoformat(),
        "dws_snapshot_date": DWS_SNAPSHOT_DATE.isoformat(),
        "stages": [
            {
                "stage_id": stage.stage_id,
                "name": stage.name,
                "layer": stage.layer,
                "description": stage.description,
                "output": stage.output,
                "depends_on": list(stage.depends_on),
            }
            for stage in STAGES
        ],
    }


def latest_pipeline_run() -> dict | None:
    with _lock:
        return copy.deepcopy(_latest_run)


def _append_log(message: str) -> None:
    with _lock:
        if _latest_run is None:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        _latest_run["logs"].append(f"{stamp}  {message.rstrip()}")
        _latest_run["logs"] = _latest_run["logs"][-_MAX_LOG_LINES:]


def _set_stage(stage_id: str, status: RunStatus, **fields: object) -> None:
    with _lock:
        if _latest_run is None:
            return
        for stage in _latest_run["stages"]:
            if stage["stage_id"] == stage_id:
                stage["status"] = status
                stage.update(fields)
                break


def _set_current_stages(stage_ids: list[str]) -> None:
    with _lock:
        if _latest_run is None:
            return
        _latest_run["current_stages"] = list(stage_ids)
        _latest_run["current_stage"] = stage_ids[0] if len(stage_ids) == 1 else None


def _add_current_stage(stage_id: str) -> None:
    with _lock:
        if _latest_run is None:
            return
        current = list(_latest_run.get("current_stages", []))
        if stage_id not in current:
            current.append(stage_id)
        _latest_run["current_stages"] = current
        _latest_run["current_stage"] = stage_id if len(current) == 1 else None


def _remove_current_stage(stage_id: str) -> None:
    with _lock:
        if _latest_run is None:
            return
        current = [
            item
            for item in _latest_run.get("current_stages", [])
            if item != stage_id
        ]
        _latest_run["current_stages"] = current
        _latest_run["current_stage"] = current[0] if len(current) == 1 else None


def _stage_args(stage: StageDefinition, business_date: date) -> tuple[str, ...]:
    if stage.stage_id == "marketing":
        return ("--strategy-date", business_date.isoformat())
    if stage.stage_id == "portfolio":
        return ("--calculation-date", business_date.isoformat())
    return stage.args


def _run_module(stage: StageDefinition, business_date: date) -> None:
    if stage.module is None:
        return
    command = [
        sys.executable,
        "-u",
        "-m",
        stage.module,
        *_stage_args(stage, business_date),
    ]
    environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        command,
        cwd=PROJECT_DIR,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if process.stdout is not None:
        for line in process.stdout:
            if line.strip():
                _append_log(f"[{stage.name}] {line.strip()}")
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"阶段“{stage.name}”执行失败，退出码 {return_code}")


def _run_module_stage(stage: StageDefinition, business_date: date) -> None:
    _set_stage(stage.stage_id, "running", started_at=_now())
    _add_current_stage(stage.stage_id)
    _append_log(f"开始：{stage.name}")
    try:
        _run_module(stage, business_date)
    except Exception as exc:
        _set_stage(stage.stage_id, "failed", finished_at=_now(), error=str(exc))
        _append_log(f"失败：{stage.name} · {exc}")
        raise
    else:
        _set_stage(stage.stage_id, "success", finished_at=_now())
        _append_log(f"完成：{stage.name}")
    finally:
        _remove_current_stage(stage.stage_id)


def _bi_snapshot(business_date: date) -> dict[str, int | str | None]:
    connection = database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM dws_customer_360")
            dws_customers = int(cursor.fetchone()["count"])
            cursor.execute(
                "SELECT COUNT(*) AS count, COUNT(DISTINCT customer_id) AS customers "
                "FROM ads_marketing_strategy WHERE strategy_date=%s",
                (business_date,),
            )
            marketing = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) AS count FROM ads_portfolio_result "
                "WHERE calculation_date=%s",
                (business_date,),
            )
            portfolio_count = int(cursor.fetchone()["count"])
    finally:
        connection.close()
    return {
        "dws_customers": dws_customers,
        "business_date": business_date.isoformat(),
        "marketing_rows": int(marketing["count"]),
        "marketing_customers": int(marketing["customers"]),
        "portfolio_scenarios": portfolio_count,
    }


def _run_pipeline(run_id: str, business_date: date) -> None:
    global _latest_run
    try:
        _append_log(f"业务日期：{business_date.isoformat()}")
        _append_log(f"DWS画像快照：{DWS_SNAPSHOT_DATE.isoformat()}")
        _run_module_stage(STAGES[0], business_date)
        _run_module_stage(STAGES[1], business_date)
        _append_log("并行启动：营销策略日批、组合优化日批")
        parallel_errors: list[Exception] = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ads-daily") as pool:
            futures = {
                pool.submit(_run_module_stage, stage, business_date): stage
                for stage in (STAGES[2], STAGES[3])
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:  # noqa: PERF203 - 两条分支均需收尾
                    parallel_errors.append(exc)
        if parallel_errors:
            raise RuntimeError(
                "并行ADS分支失败：" + "；".join(str(item) for item in parallel_errors)
            )

        bi_stage = STAGES[4]
        _set_stage(bi_stage.stage_id, "running", started_at=_now())
        _add_current_stage(bi_stage.stage_id)
        _append_log(f"开始：{bi_stage.name}")
        try:
            metrics = _bi_snapshot(business_date)
        except Exception as exc:
            _set_stage(
                bi_stage.stage_id,
                "failed",
                finished_at=_now(),
                error=str(exc),
            )
            _remove_current_stage(bi_stage.stage_id)
            raise
        _append_log(
            "[BI数据就绪] "
            f"DWS客户={metrics['dws_customers']}，"
            f"营销客户={metrics['marketing_customers']}，"
            f"营销策略={metrics['marketing_rows']}，"
            f"组合场景={metrics['portfolio_scenarios']}"
        )
        _set_stage(
            bi_stage.stage_id,
            "success",
            finished_at=_now(),
            metrics=metrics,
        )
        _remove_current_stage(bi_stage.stage_id)
        _append_log(f"完成：{bi_stage.name}")
        with _lock:
            if _latest_run is not None and _latest_run["run_id"] == run_id:
                _latest_run.update(
                    status="success",
                    current_stage=None,
                    current_stages=[],
                    finished_at=_now(),
                )
        _append_log("全链路执行成功，经营看板可以刷新最新指标。")
    except Exception as exc:  # noqa: BLE001 - 后台任务必须固化失败状态
        _append_log(f"失败：{exc}")
        with _lock:
            if _latest_run is None or _latest_run["run_id"] != run_id:
                return
            for stage in _latest_run["stages"]:
                if stage["status"] == "pending":
                    stage["status"] = "skipped"
            _latest_run.update(
                status="failed",
                current_stage=None,
                current_stages=[],
                finished_at=_now(),
                error=str(exc),
            )


def start_pipeline_run(business_date: date = DEFAULT_BUSINESS_DATE) -> dict:
    global _active_thread, _latest_run
    with _lock:
        if _latest_run is not None and _latest_run["status"] == "running":
            raise PipelineBusyError("已有数据任务正在执行，请等待当前批次完成")
        run_id = f"manual_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        _latest_run = {
            "run_id": run_id,
            "pipeline_id": "wealth_warehouse_daily",
            "trigger": "manual",
            "business_date": business_date.isoformat(),
            "status": "running",
            "current_stage": None,
            "current_stages": [],
            "started_at": _now(),
            "finished_at": None,
            "error": None,
            "stages": [
                {
                    "stage_id": stage.stage_id,
                    "name": stage.name,
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                }
                for stage in STAGES
            ],
            "logs": [],
        }
        _active_thread = threading.Thread(
            target=_run_pipeline,
            args=(run_id, business_date),
            name=f"warehouse-pipeline-{run_id}",
            daemon=True,
        )
        _active_thread.start()
        return copy.deepcopy(_latest_run)


__all__ = [
    "DEFAULT_BUSINESS_DATE",
    "PipelineBusyError",
    "latest_pipeline_run",
    "pipeline_definition",
    "start_pipeline_run",
]
