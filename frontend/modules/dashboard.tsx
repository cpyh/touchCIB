"use client";

import { useEffect, useMemo, useState } from "react";

import {
  DashboardApiError,
  DashboardOverview,
  DataStatus,
  getDashboardOverview,
} from "../shared/dashboard-api";
import { channelNames, PageHead, Status } from "../shared/ui";

const scenarios = Array.from({ length: 20 }, (_, index) => `S${String(index + 1).padStart(2, "0")}`);
const statusText: Record<DataStatus, string> = {
  READY: "数据已就绪",
  NOT_READY: "待生成",
  INVALID: "结果校验异常",
  NOT_STARTED: "尚未执行",
};

function percent(value: number | null | undefined, digits = 1) {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function compactMoney(value: number | null | undefined) {
  if (value == null) return "—";
  if (Math.abs(value) >= 100_000_000) return `¥ ${(value / 100_000_000).toFixed(2)}亿`;
  if (Math.abs(value) >= 10_000) return `¥ ${(value / 10_000).toFixed(1)}万`;
  return `¥ ${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
}

function exactMoney(value: number | null | undefined) {
  return value == null ? "—" : `¥ ${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function metric(value: number | null | undefined, digits = 3) {
  return value == null ? "—" : value.toFixed(digits);
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function ResultStatus({ status }: { status: DataStatus }) {
  return <Status warn={status !== "READY"}>{statusText[status]}</Status>;
}

function EmptyState({ status, text }: { status: DataStatus; text: string }) {
  return <div className={`dashboard-empty ${status === "INVALID" ? "invalid" : ""}`}><b>{statusText[status]}</b><span>{text}</span></div>;
}

export function DashboardPage() {
  const [scenarioId, setScenarioId] = useState("S01");
  const [dashboard, setDashboard] = useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getDashboardOverview(scenarioId, controller.signal)
      .then(setDashboard)
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(requestError instanceof DashboardApiError ? requestError.message : "可视化看板加载失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scenarioId, refreshKey]);

  const maxRiskCount = useMemo(() => Math.max(...(dashboard?.risk_distribution.map(item => item.count) ?? [1]), 1), [dashboard]);
  const maxIntentCount = useMemo(() => Math.max(...(dashboard?.a1_performance.probability_distribution.map(item => item.count) ?? [1]), 1), [dashboard]);
  const maxChannelCount = useMemo(() => Math.max(...(dashboard?.a2_performance.channel_distribution.map(item => item.count) ?? [1]), 1), [dashboard]);

  function selectScenario(nextScenario: string) {
    if (nextScenario === scenarioId) return;
    setScenarioId(nextScenario);
    setLoading(true);
    setError("");
  }

  function refresh() {
    setLoading(true);
    setError("");
    setRefreshKey(value => value + 1);
  }

  if (!dashboard && loading) {
    return <><PageHead title="可视化经营看板" description="汇总业务经营、算法结果、组合配置与营销执行状态。" action={<Status>正在读取真实数据</Status>} /><div className="dashboard-loading"><i /><b>正在聚合可视化看板数据…</b><span>读取 MySQL 与正式算法结果文件</span></div></>;
  }

  if (!dashboard && error) {
    return <><PageHead title="可视化经营看板" description="汇总业务经营、算法结果、组合配置与营销执行状态。" action={<Status warn>接口连接失败</Status>} /><div className="dashboard-error"><b>无法读取可视化看板</b><p>{error}</p><button className="secondary" onClick={refresh}>重新连接</button></div></>;
  }

  if (!dashboard) return null;

  const business = dashboard.business_metrics;
  const a1 = dashboard.a1_performance;
  const a2 = dashboard.a2_performance;
  const portfolio = dashboard.portfolio;
  const funnel = dashboard.marketing_funnel;
  const funnelRows = [
    ["目标客户", funnel.target_customer_count],
    ["已生成策略", funnel.generated_customer_count],
    ["已触达", funnel.contacted_customer_count],
    ["已响应", funnel.responded_customer_count],
  ] as const;
  const funnelMax = Math.max(funnel.target_customer_count, 1);

  return <>
    <PageHead
      title="可视化经营看板"
      description="统一展示业务规模、客户结构、算法证据、组合配置与营销执行结果。"
      action={<div className="dashboard-actions"><span className={loading ? "refresh-state busy" : "refresh-state"}>{loading ? "正在刷新" : `更新于 ${formatTime(dashboard.generated_at)}`}</span><button className="secondary" disabled={loading} onClick={refresh}>↻ 刷新数据</button></div>}
    />

    {error && <div className="dashboard-inline-error"><span>本次刷新失败：{error}</span><button onClick={refresh}>重试</button></div>}

    <section className="business-kpis" aria-label="核心业务指标">
      <article><small>客户总数</small><strong>{business.customer_count.toLocaleString()}</strong><span>ODS 客户记录</span></article>
      <article><small>客户资产管理规模</small><strong>{compactMoney(business.total_aum)}</strong><span title={exactMoney(business.total_aum)}>客户 AUM 总额</span></article>
      <article><small>产品与持仓</small><strong>{business.product_count.toLocaleString()} 款</strong><span title={exactMoney(business.total_holding_amount)}>持仓 {compactMoney(business.total_holding_amount)}</span></article>
      <article><small>历史营销触达</small><strong>{business.historical_contact_count.toLocaleString()}</strong><span>响应率 {percent(business.historical_response_rate)}</span></article>
    </section>

    <div className="dashboard-board">
      <section className="card dashboard-panel risk-panel">
        <div className="section-head"><div><h2>客户风险分布</h2><p>R1—R5风险偏好客户数量</p></div><Status>{business.customer_count.toLocaleString()} 位客户</Status></div>
        <div className="dashboard-bars vertical-bars">{dashboard.risk_distribution.map((item, index) => <div key={item.risk_level}><em>{item.count.toLocaleString()}</em><i className={index === 2 ? "gold" : ""} style={{ height: `${Math.max(item.count / maxRiskCount * 100, 3)}%` }} /><b>{item.risk_level}</b><span>{item.risk_label}</span></div>)}</div>
      </section>

      <section className="card dashboard-panel holding-panel">
        <div className="section-head"><div><h2>持仓类型分布</h2><p>总持仓 {compactMoney(business.total_holding_amount)}</p></div><Status>真实持仓</Status></div>
        <div className="distribution-list">{dashboard.holding_distribution.map(item => <div key={item.product_type}><span><b>{item.product_type}</b><em>{compactMoney(item.holding_amount)}</em></span><i><b style={{ width: `${(item.ratio ?? 0) * 100}%` }} /></i><small>{percent(item.ratio)}</small></div>)}</div>
      </section>

      <section className="card dashboard-panel algorithm-panel wide">
        <div className="section-head"><div><h2>A1 · 营销响应预测</h2><p>离线验证指标，仅作为本地模型效果证据</p></div><ResultStatus status={a1.status} /></div>
        {a1.status === "READY" ? <div className="algorithm-layout"><div className="algorithm-metrics"><article><small>AUC</small><strong>{metric(a1.auc)}</strong><span>离线验证</span></article><article><small>最优 F1</small><strong>{metric(a1.f1)}</strong><span>阈值扫描结果</span></article><article><small>Lift@10%</small><strong>{metric(a1.lift_at_10, 2)}</strong><span>前10%人群提升</span></article><article><small>平均响应概率</small><strong>{percent(a1.mean_probability)}</strong><span>{a1.prediction_count ? `${a1.prediction_count.toLocaleString()} 条预测` : "MySQL预测结果"}</span></article></div><div className="intent-distribution"><h3>预测意向分层</h3>{a1.probability_distribution.map(item => <div key={item.bucket}><span>{item.bucket}</span><i><b style={{ width: `${item.count / maxIntentCount * 100}%` }} /></i><em>{item.count.toLocaleString()}</em></div>)}</div></div> : <EmptyState status={a1.status} text="A1验证指标或预测结果尚未准备完成。" />}
      </section>

      <section className="card dashboard-panel algorithm-panel">
        <div className="section-head"><div><h2>A2 · Top3营销策略</h2><p>目标客户覆盖与渠道分布</p></div><ResultStatus status={a2.status} /></div>
        {a2.status === "READY" ? <><div className="a2-summary"><article><small>目标客户</small><strong>{a2.target_customer_count.toLocaleString()}</strong></article><article><small>完整生成</small><strong>{a2.generated_customer_count.toLocaleString()}</strong></article><article><small>覆盖率</small><strong>{percent(a2.coverage_rate)}</strong></article></div><div className="channel-distribution">{a2.channel_distribution.map(item => <div key={item.channel}><span>{channelNames[item.channel] ?? item.channel}</span><i><b style={{ width: `${item.count / maxChannelCount * 100}%` }} /></i><em>{item.count.toLocaleString()}</em></div>)}</div><p className="metric-note">HitRate@3：官方隐藏购买标签，暂不可计算</p></> : <EmptyState status={a2.status} text={a2.status === "INVALID" ? "策略文件未通过覆盖率、Top3或字段完整性校验。" : "A2策略结果尚未生成。"} />}
      </section>

      <section className="card dashboard-panel funnel-panel">
        <div className="section-head"><div><h2>营销执行漏斗</h2><p>策略生成—触达—响应闭环</p></div><ResultStatus status={funnel.status} /></div>
        <div className="funnel-list">{funnelRows.map(([label, count], index) => <div key={label}><span><b>{label}</b><em>{count.toLocaleString()}</em></span><i><b style={{ width: `${count / funnelMax * 100}%` }} /></i><small>{index === 0 ? "100%" : percent(count / funnelMax)}</small></div>)}</div>
        {funnel.status === "NOT_STARTED" && <p className="metric-note warn-note">尚未产生营销执行事件，触达与响应不补充模拟数据。</p>}
      </section>

      <section className="card dashboard-panel portfolio-panel full-width">
        <div className="section-head"><div><h2>Part B · 组合配置场景</h2><p>读取正式配置与审计结果，可切换场景下钻</p></div><div className="scenario-control"><label htmlFor="dashboard-scenario">场景</label><select id="dashboard-scenario" value={scenarioId} disabled={loading} onChange={event => selectScenario(event.target.value)}>{scenarios.map(item => <option key={item}>{item}</option>)}</select><ResultStatus status={portfolio.status} /></div></div>
        {portfolio.status === "READY" ? <><div className="portfolio-summary"><article><small>配置资金</small><strong>{compactMoney(portfolio.total_amount)}</strong></article><article><small>预期收益率</small><strong>{percent(portfolio.expected_return, 2)}</strong></article><article><small>组合波动率</small><strong>{percent(portfolio.volatility, 2)}</strong></article><article><small>效用值</small><strong>{metric(portfolio.utility, 4)}</strong></article><article><small>约束审计</small><strong className={portfolio.constraints_satisfied ? "pass" : "fail"}>{portfolio.constraints_satisfied ? "全部通过" : "未通过"}</strong></article></div><div className="portfolio-details"><div><h3>按产品类型配置</h3><div className="allocation-types">{portfolio.allocation_by_product_type.map(item => <div key={item.product_type}><span>{item.product_type}</span><i><b style={{ width: `${item.weight * 100}%` }} /></i><em>{percent(item.weight)}</em></div>)}</div><p className="portfolio-audit">现金权重 {percent(portfolio.cash_weight, 3)} · 最优性差距 {metric(portfolio.optimality_gap, 6)}</p></div><div className="table portfolio-table"><table><thead><tr><th>产品</th><th>类型</th><th>风险</th><th>权重</th><th>配置金额</th></tr></thead><tbody>{portfolio.allocation_items.map(item => <tr key={item.product_id}><td><b>{item.product_name}</b><small>{item.product_id}</small></td><td>{item.product_type}</td><td><span className="risk-tag">{item.risk_level}</span></td><td>{percent(item.weight, 2)}</td><td>{exactMoney(item.allocation_amount)}</td></tr>)}</tbody></table></div></div></> : <EmptyState status={portfolio.status} text={portfolio.status === "INVALID" ? "该场景结果未通过约束或完整性校验。" : `${scenarioId} 场景结果尚未准备完成。`} />}
      </section>
    </div>
  </>;
}
