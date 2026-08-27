"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getLatestPipelineRun,
  PipelineDefinition,
  PipelineRun,
  PipelineStageDefinition,
  PipelineStageRun,
  PipelineStatus,
  startPipelineRun,
} from "../shared/pipeline-api";
import { formatDateTime } from "../shared/format";
import { PageHead } from "../shared/ui";


const statusNames: Record<PipelineStatus, string> = {
  pending: "等待执行",
  running: "正在运行",
  success: "执行成功",
  failed: "执行失败",
  skipped: "已跳过",
};


function StageNode({
  definition,
  run,
}: {
  definition?: PipelineStageDefinition;
  run?: PipelineStageRun;
}) {
  if (!definition) return null;
  const status = run?.status ?? "pending";
  return (
    <article className={`pipeline-node ${status}`}>
      <header>
        <span>{definition.layer}</span>
        <em><i />{statusNames[status]}</em>
      </header>
      <h3>{definition.name}</h3>
      <p>{definition.description}</p>
      <footer><b>产出</b><span>{definition.output}</span></footer>
    </article>
  );
}


export function PipelineTaskCenter({
  businessDate,
  onBusinessDateChange,
  onOpenOverview,
}: {
  businessDate: string;
  onBusinessDateChange: (value: string) => void;
  onOpenOverview: () => void;
}) {
  const [definition, setDefinition] = useState<PipelineDefinition | null>(null);
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const snapshot = await getLatestPipelineRun(signal);
      setDefinition(snapshot.definition);
      setRun(snapshot.run);
      setError("");
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError(requestError instanceof Error ? requestError.message : "数据任务状态读取失败");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getLatestPipelineRun(controller.signal)
      .then((snapshot) => {
        setDefinition(snapshot.definition);
        setRun(snapshot.run);
        setError("");
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(requestError instanceof Error ? requestError.message : "数据任务状态读取失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (run?.status !== "running") return;
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh, run?.status]);

  const stageDefinitions = useMemo(
    () => Object.fromEntries((definition?.stages ?? []).map((stage) => [stage.stage_id, stage])),
    [definition]
  );
  const stageRuns = useMemo(
    () => Object.fromEntries((run?.stages ?? []).map((stage) => [stage.stage_id, stage])),
    [run]
  );
  const completed = run?.stages.filter((stage) => stage.status === "success").length ?? 0;
  const progress = Math.round((completed / Math.max(definition?.stages.length ?? 5, 1)) * 100);
  const isRunning = run?.status === "running";

  async function start() {
    setStarting(true);
    setError("");
    try {
      const result = await startPipelineRun(businessDate);
      setRun(result.run);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "数据任务启动失败");
      await refresh();
    } finally {
      setStarting(false);
    }
  }

  return (
    <>
      <div className="dashboard-view-tabs" aria-label="可视化看板页面切换">
        <button onClick={onOpenOverview}>经营分析</button>
        <button className="on">数据任务中心</button>
      </div>

      <PageHead
        title="数据任务中心"
        description="手动触发固定业务日批，实时观察 ODS、DWD、DWS、ADS 到 BI 的完整数据链路。"
        action={
          <div className="pipeline-run-controls">
            <label>
              <span>业务日期</span>
              <input
                type="date"
                value={businessDate}
                max={definition?.default_business_date}
                disabled={starting || isRunning || loading}
                onChange={(event) => onBusinessDateChange(event.target.value)}
                aria-label="选择日批业务日期"
              />
            </label>
            <button className="primary pipeline-run-button" disabled={starting || isRunning || loading || !businessDate} onClick={() => void start()}>
              {starting ? "正在启动…" : isRunning ? "任务执行中" : "▶ 执行全链路"}
            </button>
          </div>
        }
      />

      {error && <div className="pipeline-alert"><b>任务提示</b><span>{error}</span></div>}

      <section className="pipeline-summary card">
        <div>
          <small>最近运行日期</small>
          <strong>{run?.business_date ?? "尚未运行"}</strong>
        </div>
        <div>
          <small>DWS基准快照</small>
          <strong>{definition?.dws_snapshot_date ?? "—"}</strong>
        </div>
        <div>
          <small>当前状态</small>
          <strong className={run?.status ?? "idle"}>
            {loading ? "读取中" : run ? statusNames[run.status] : "等待首次执行"}
          </strong>
        </div>
        <div>
          <small>最近批次</small>
          <strong>{run?.run_id ?? "—"}</strong>
        </div>
        <div>
          <small>完成进度</small>
          <strong>{completed}/{definition?.stages.length ?? 5} 节点</strong>
        </div>
        <i><b style={{ width: `${isRunning ? Math.max(progress, 3) : progress}%` }} /></i>
      </section>

      <div className="pipeline-workspace">
        <section className="pipeline-canvas card">
          <header>
            <div><span>WEALTH WAREHOUSE DAILY</span><h2>业务数仓日批 DAG</h2></div>
            <em><i />固定命令白名单</em>
          </header>

          <div className="pipeline-dag">
            <StageNode definition={stageDefinitions.warehouse} run={stageRuns.warehouse} />
            <div className="dag-arrow"><i />↓</div>
            <StageNode definition={stageDefinitions.quality} run={stageRuns.quality} />
            <div className="dag-split"><i /><span>↓</span><span>↓</span></div>
            <div className="dag-branches">
              <StageNode definition={stageDefinitions.marketing} run={stageRuns.marketing} />
              <StageNode definition={stageDefinitions.portfolio} run={stageRuns.portfolio} />
            </div>
            <div className="dag-join"><span>↘</span><i /><span>↙</span></div>
            <StageNode definition={stageDefinitions.bi} run={stageRuns.bi} />
          </div>
        </section>

        <aside className="pipeline-console card">
          <header>
            <div><small>RUN MONITOR</small><h2>运行监控</h2></div>
            <span className={run?.status ?? "idle"}><i />{run ? statusNames[run.status] : "空闲"}</span>
          </header>

          <div className="pipeline-run-meta">
            <div><small>触发方式</small><b>{run ? "页面手动触发" : "—"}</b></div>
            <div><small>业务日期</small><b>{run?.business_date ?? "—"}</b></div>
            <div><small>开始时间</small><b>{run ? formatDateTime(run.started_at) : "—"}</b></div>
            <div><small>当前节点</small><b>{run?.current_stages?.length ? run.current_stages.map((stageId) => stageDefinitions[stageId]?.name).filter(Boolean).join("、") : run?.status === "success" ? "全部完成" : "—"}</b></div>
          </div>

          <div className="pipeline-log" aria-live="polite">
            {run?.logs.length ? run.logs.map((line, index) => <p key={`${index}-${line}`}>{line}</p>) : (
              <div><b>等待任务启动</b><span>点击“执行全链路”后，这里会实时显示各节点日志。</span></div>
            )}
          </div>

          {run?.status === "success" && (
            <button className="secondary full" onClick={onOpenOverview}>查看刷新后的经营看板 →</button>
          )}
          {run?.status === "failed" && <p className="pipeline-error">{run.error}</p>}
        </aside>
      </div>

      <section className="pipeline-note">
        <b>演示说明</b>
        <p>日批覆盖截至业务日期已注册的全部客户，不依赖人群包。营销与组合优化分支在质量门禁通过后并行执行；同日补跑采用幂等覆盖，页面按所选日期精确读取 ADS。</p>
      </section>
    </>
  );
}
