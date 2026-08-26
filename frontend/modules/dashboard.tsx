"use client";

import { useEffect, useState } from "react";

import { api } from "../shared/api";
import { channelNames, Metric, PageHead, Status, riskNames } from "../shared/ui";

interface Kpi {
  kpi_id: string;
  label: string;
  target: number;
  actual: number;
  completion_rate: number;
  unit: string;
}

interface DashboardData {
  model_metrics: {
    auc: number | null;
    best_f1: number | null;
    lift_at_10_percent: number | null;
  };
  prediction_stats: {
    total: number;
    mean_prob: number;
    high_intent: number;
    mid_intent: number;
    low_intent: number;
  };
  strategy_stats: {
    rows: number;
    customers: number;
    channel_distribution: Record<string, number>;
  };
  partb_stats: { scenarios?: number; total_utility?: number };
  customer_stats: {
    total: number;
    total_aum: number;
    risk_distribution: Record<string, number>;
  };
  channel_stats: {
    overall_contacts: number;
    overall_response_rate: number;
    channels: Record<string, { contacts: number; response_rate: number }>;
  };
  funnel: { stages: { stage: string; count: number }[]; pending: number };
  kpis: Kpi[];
  data_layers: Record<string, number | null>;
}

function formatKpi(value: number, unit: string) {
  return unit === "%" ? `${(value * 100).toFixed(1)}%` : `${value}${unit}`;
}

export function DashboardPage({ notify }: { notify: (message: string) => void }) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);

  useEffect(() => {
    api<DashboardData>("/dashboard/summary")
      .then(setDashboard)
      .catch((error) => notify(`经营看板加载失败：${error.message}`));
  }, []);

  if (!dashboard) {
    return (
      <>
        <PageHead title="Part C/D · 经营与工程看板" description="汇总算法、数仓和运营执行结果。" action={<Status>加载中</Status>} />
        <div className="empty-result"><b>正在加载评分证据…</b></div>
      </>
    );
  }

  const riskRows = Object.entries(dashboard.customer_stats.risk_distribution)
    .sort((left, right) => left[0].localeCompare(right[0]));
  const riskMax = Math.max(...riskRows.map((item) => item[1]), 1);
  const channelRows = Object.entries(dashboard.channel_stats.channels);

  return (
    <>
      <PageHead
        title="Part C/D · 经营与工程看板"
        description="把模型效果、数据分层、正式提交结果和营销执行事件放在同一看板，证明方案可复现、可解释、可运营。"
        action={<span className="date-chip">分析基准日：2026-03-31</span>}
      />

      <section className="score-section">
        <div className="section-head"><div><h2>算法评分证据</h2><p>直接对应A1、A2与Part B赛事指标</p></div><Status>random_state=42</Status></div>
        <div className="dashboard-kpis">
          <Metric label="A1 · AUC" value={dashboard.model_metrics.auc?.toFixed(3) ?? "—"} note="高锚点0.85" gold />
          <Metric label="A1 · F1" value={dashboard.model_metrics.best_f1?.toFixed(3) ?? "—"} note="后台扫描最优阈值" />
          <Metric label="A1 · Lift@10%" value={dashboard.model_metrics.lift_at_10_percent?.toFixed(2) ?? "—"} note="高锚点3.3" />
          <Metric label="A2 · 策略规模" value={dashboard.strategy_stats.rows.toLocaleString()} note={`${dashboard.strategy_stats.customers.toLocaleString()}客户×Top3`} />
          <Metric label="Part B · 可行场景" value={`${dashboard.partb_stats.scenarios ?? 0}/20`} note={`总效用 ${dashboard.partb_stats.total_utility?.toFixed(4) ?? "—"}`} />
        </div>
      </section>

      <div className="dashboard engineering-dashboard">
        <section className="card chart wide">
          <div className="section-head"><div><h2>数据分层与应用链路</h2><p>MySQL实体表行数；不可用时显示“—”</p></div><Status>Part C工程证据</Status></div>
          <div className="layer-flow">
            {[
              ["ODS", "原始贴源", dashboard.data_layers.ods],
              ["DWD", "维度与事实", dashboard.data_layers.dwd],
              ["DWS", "客户360画像", dashboard.data_layers.dws],
              ["ADS/APP", "预测与运营事件", dashboard.data_layers.ads],
            ].map((layer, index) => (
              <div key={String(layer[0])}>
                <b>{layer[0]}</b><strong>{typeof layer[2] === "number" ? layer[2].toLocaleString() : "—"}</strong><span>{layer[1]}</span>
                {index < 3 && <i>→</i>}
              </div>
            ))}
          </div>
          <div className="engineering-facts">
            <span><b>41项</b>SQL质量规则</span>
            <span><b>as-of</b>严格时间截断</span>
            <span><b>双源</b>CSV复现 / MySQL平台</span>
            <span><b>版本化</b>模型与特征口径</span>
          </div>
        </section>

        <section className="card chart">
          <h2>正式提交产物</h2>
          <div className="submission-list">
            <div><b>A1</b><span><strong>partA_prediction.csv</strong><small>{dashboard.prediction_stats.total.toLocaleString()}条 · 概率完整覆盖</small></span><Status>已生成</Status></div>
            <div><b>A2</b><span><strong>partA_strategy.csv</strong><small>{dashboard.strategy_stats.rows.toLocaleString()}行 · 每客户恰好Top3</small></span><Status>已生成</Status></div>
            <div><b>B</b><span><strong>partB_allocation.csv</strong><small>{dashboard.partb_stats.scenarios ?? 0}个场景 · 约束通过</small></span><Status>已生成</Status></div>
          </div>
        </section>

        <section className="card chart wide">
          <div className="section-head"><div><h2>营销执行闭环</h2><p>策略生成→触达→响应，事件落库后重新进入本页即可刷新</p></div><Status>Part D平台联动</Status></div>
          <div className="steps">
            {dashboard.funnel.stages.map((stage, index) => (
              <div className="on" key={stage.stage}><i>{index + 1}</i><b>{stage.count.toLocaleString()}</b><span>{stage.stage}</span></div>
            ))}
          </div>
          <div className="kpi-list">
            {dashboard.kpis.map((kpi) => (
              <div key={kpi.kpi_id}>
                <span><strong>{kpi.label}</strong><small>目标 {formatKpi(kpi.target, kpi.unit)}</small></span>
                <i><b style={{ width: `${Math.round(kpi.completion_rate * 100)}%` }} /></i>
                <em>{formatKpi(kpi.actual, kpi.unit)} · {Math.round(kpi.completion_rate * 100)}%</em>
              </div>
            ))}
          </div>
        </section>

        <section className="card chart">
          <h2>客户风险分布</h2>
          <div className="bars compact-bars">
            {riskRows.map((item, index) => (
              <div key={item[0]}><em>{item[1].toLocaleString()}</em><i className={index === 2 ? "goldbar" : ""} style={{ height: `${item[1] / riskMax * 100}%` }} /><b>{item[0]}</b><span>{riskNames[item[0]]}</span></div>
            ))}
          </div>
        </section>

        <section className="card chart">
          <h2>历史渠道响应率</h2>
          <div className="channel">
            {channelRows.map(([channel, values]) => (
              <div key={channel}><span>{channelNames[channel]}</span><i><b style={{ width: `${values.response_rate * 100}%` }} /></i><em>{(values.response_rate * 100).toFixed(1)}%</em></div>
            ))}
          </div>
          <p className="insight"><b>运营解释</b> 渠道选择由客户等级、App状态和投诉规则共同约束，不仅依赖模型概率。</p>
        </section>
      </div>
    </>
  );
}
