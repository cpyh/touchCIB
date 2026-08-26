"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "../shared/api";
import { channelNames, Metric, PageHead, Status, Timeline } from "../shared/ui";

type MarketingTab = "a1" | "a2" | "track";

interface RosterRow {
  contact_id: string;
  customer_id: string;
  product_id: string;
  product_name: string;
  risk_level: string;
  channel: string;
  contact_date: string;
  response_prob: number;
}

interface RuleTrace {
  rule_id: string;
  passed: boolean;
  reason: string;
}

interface StrategyItem {
  strategy_id: string;
  rank: number;
  product_id: string;
  product_name: string;
  risk_level: string;
  expected_return: number;
  recommended_channel: string;
  recommended_time: string;
  marketing_script: string;
  status: string;
  rule_trace: RuleTrace[];
}

interface CampaignEvent {
  campaign_event_id: number;
  strategy_id: string;
  event_type: "sent" | "responded";
  occurred_at: string;
  product_id: string | null;
  amount: number | null;
}

interface MarketingSummary {
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
  };
}

interface MarketingPageProps {
  initialCustomerId: string;
  onOpenCustomer: (customerId: string) => void;
  notify: (message: string) => void;
}

export function MarketingPage({
  initialCustomerId,
  onOpenCustomer,
  notify,
}: MarketingPageProps) {
  const [tab, setTab] = useState<MarketingTab>("a1");
  const [roster, setRoster] = useState<RosterRow[]>([]);
  const [summary, setSummary] = useState<MarketingSummary | null>(null);
  const [query, setQuery] = useState("");
  const [channelFilter, setChannelFilter] = useState("全部渠道");
  const [intentFilter, setIntentFilter] = useState("全部意向");
  const [strategyInput, setStrategyInput] = useState(initialCustomerId || "C000010");
  const [strategyCustomerId, setStrategyCustomerId] = useState(initialCustomerId || "C000010");
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [trackedStrategyId, setTrackedStrategyId] = useState("");
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadRoster();
    void loadSummary();
  }, []);

  useEffect(() => {
    if (initialCustomerId) {
      setStrategyInput(initialCustomerId);
      void loadStrategies(initialCustomerId, true);
    }
  }, [initialCustomerId]);

  async function loadRoster() {
    try {
      const data = await api<{ customers: RosterRow[] }>(
        "/marketing/roster?size=200&sort=prob_desc",
      );
      setRoster(data.customers);
    } catch (error) {
      notify(`A1名单加载失败：${(error as Error).message}`);
    }
  }

  async function loadSummary() {
    try {
      setSummary(await api<MarketingSummary>("/dashboard/summary"));
    } catch (error) {
      notify(`模型指标加载失败：${(error as Error).message}`);
    }
  }

  async function refreshEvents(customerId: string) {
    try {
      const data = await api<{ events: CampaignEvent[] }>(
        `/campaign/events?customer_id=${encodeURIComponent(customerId)}`,
      );
      setEvents(data.events);
    } catch {
      setEvents([]);
    }
  }

  async function loadStrategies(customerId: string, openTab = true) {
    const normalized = customerId.trim().toUpperCase();
    if (!normalized) {
      notify("请输入客户编号");
      return;
    }
    setBusy(true);
    try {
      const data = await api<{ items: StrategyItem[] }>(
        `/customers/${encodeURIComponent(normalized)}/strategies`,
      );
      setStrategies(data.items);
      setStrategyCustomerId(normalized);
      setStrategyInput(normalized);
      setTrackedStrategyId((current) =>
        data.items.some((item) => item.strategy_id === current)
          ? current
          : data.items[0]?.strategy_id ?? "",
      );
      await refreshEvents(normalized);
      if (openTab) setTab("a2");
    } catch (error) {
      notify(`A2策略加载失败：${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function recordEvent(payload: Record<string, unknown>) {
    setBusy(true);
    try {
      const data = await api<CampaignEvent>("/campaign/events", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      notify(`事件已落库：${data.event_type}`);
      await loadStrategies(strategyCustomerId, false);
      await loadSummary();
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const filteredRoster = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return roster.filter((row) => {
      const fuzzy = !keyword || [row.customer_id, row.product_id, row.product_name]
        .some((value) => value.toLowerCase().includes(keyword));
      const channelMatched = channelFilter === "全部渠道" || channelNames[row.channel] === channelFilter;
      const intent = row.response_prob >= 0.7 ? "高意向" : row.response_prob >= 0.3 ? "中意向" : "低意向";
      return fuzzy && channelMatched && (intentFilter === "全部意向" || intentFilter === intent);
    });
  }, [channelFilter, intentFilter, query, roster]);

  const trackedStrategy = strategies.find((item) => item.strategy_id === trackedStrategyId) ?? strategies[0];
  const timeline = [
    ["策略生成", "04-15", "A1概率、协同过滤和规则引擎共同生成Top 3。"],
    ...events.filter((event) => event.event_type === "sent").map((event) => [
      "渠道触达",
      event.occurred_at.replace("T", " ").slice(5, 16),
      `${event.strategy_id} 已记录sent事件。`,
    ]),
    ...events.filter((event) => event.event_type === "responded").map((event) => [
      "响应归因",
      event.occurred_at.replace("T", " ").slice(5, 16),
      `购买${event.product_id}，金额¥${event.amount?.toLocaleString("zh-CN") ?? "—"}。`,
    ]),
  ];

  return (
    <>
      <PageHead
        title="Part A · 精准营销运营工作台"
        description="A1响应概率驱动客户排序，A2输出Top 3产品、渠道、时段与话术，并通过规则轨迹和执行事件形成运营闭环。"
        action={<Status>Part D现场验收主页面</Status>}
      />

      <section className="card batch">
        <div><b>A</b><span><strong>2026年4月财富客户营销任务</strong><small>分析基准日 2026-03-31 · 策略日 2026-04-15</small></span></div>
        <div className="file-box"><b>A1</b><span><strong>partA_prediction.csv</strong><small>8,000条预测</small></span><Status>格式通过</Status></div>
        <div className="file-box"><b>A2</b><span><strong>partA_strategy.csv</strong><small>2,000客户 × Top3</small></span><Status>格式通过</Status></div>
        <Status>严格as-of截断</Status>
      </section>

      <div className="main-tabs">
        <button className={tab === "a1" ? "on" : ""} onClick={() => setTab("a1")}>A1 响应预测 <span>8,000</span></button>
        <button className={tab === "a2" ? "on" : ""} onClick={() => setTab("a2")}>A2 Top 3策略 <span>2,000</span></button>
        <button className={tab === "track" ? "on" : ""} onClick={() => setTab("track")}>执行与归因 <span>{events.length}</span></button>
      </div>

      {tab === "a1" && (
        <section className="card marketing">
          <div className="metrics">
            <Metric label="验证 AUC" value={summary?.model_metrics.auc?.toFixed(3) ?? "—"} note="满分锚点0.85" gold />
            <Metric label="最佳 F1" value={summary?.model_metrics.best_f1?.toFixed(3) ?? "—"} note="后台自动扫描阈值" />
            <Metric label="Lift@10%" value={summary?.model_metrics.lift_at_10_percent?.toFixed(2) ?? "—"} note="满分锚点3.3" />
            <Metric label="高意向机会" value={summary?.prediction_stats.high_intent.toLocaleString() ?? "—"} note="response_prob≥70%" />
          </div>
          <div className="model-note">
            <b>A1解释口径</b>
            <span>每条预测以contact_date为目标时点，持仓、行为和历史触达特征只取严格早于目标日的数据。</span>
          </div>
          <div className="toolbar">
            <input placeholder="搜索客户ID或产品" value={query} onChange={(event) => setQuery(event.target.value)} />
            <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
              {["全部渠道", "短信", "电话", "App推送", "客户经理"].map((item) => <option key={item}>{item}</option>)}
            </select>
            <select value={intentFilter} onChange={(event) => setIntentFilter(event.target.value)}>
              {["全部意向", "高意向", "中意向", "低意向"].map((item) => <option key={item}>{item}</option>)}
            </select>
          </div>
          <div className="table">
            <table>
              <thead><tr>{["客户", "产品", "渠道", "目标日期", "响应概率", "意向等级", ""].map((header) => <th key={header}>{header}</th>)}</tr></thead>
              <tbody>
                {filteredRoster.map((row) => (
                  <tr key={row.contact_id}>
                    <td><b>{row.customer_id}</b><small>{row.contact_id}</small></td>
                    <td>{row.product_name}<small>{row.product_id} · {row.risk_level}</small></td>
                    <td>{channelNames[row.channel]}</td>
                    <td>{row.contact_date}</td>
                    <td><div className="prob"><b>{(row.response_prob * 100).toFixed(1)}%</b><i><em style={{ width: `${row.response_prob * 100}%` }} /></i></div></td>
                    <td><span className={row.response_prob >= 0.7 ? "intent high" : "intent"}>{row.response_prob >= 0.7 ? "高意向" : row.response_prob >= 0.3 ? "中意向" : "低意向"}</span></td>
                    <td><button className="row-action" onClick={() => void loadStrategies(row.customer_id)}>查看Top3 ›</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "a2" && (
        <section>
          <div className="card customer-strip">
            <div className="avatar">{strategyCustomerId.slice(-2)}</div>
            <span><small>当前目标客户</small><strong>{strategyCustomerId}</strong><em>A1概率 + 协同过滤 + 规则引擎 → Top3</em></span>
            <input value={strategyInput} onChange={(event) => setStrategyInput(event.target.value)} placeholder="客户编号" />
            <button className="secondary" disabled={busy} onClick={() => void loadStrategies(strategyInput)}>查询策略</button>
            <button className="secondary" onClick={() => onOpenCustomer(strategyCustomerId)}>查看360画像</button>
          </div>

          <div className="strategy-grid">
            {strategies.map((strategy) => {
              const passed = strategy.rule_trace.filter((item) => item.passed);
              const failed = strategy.rule_trace.filter((item) => !item.passed);
              return (
                <article className="card strategy" key={strategy.strategy_id}>
                  <div className="rank">TOP {strategy.rank}<span>规则通过 {passed.length}/{strategy.rule_trace.length}</span></div>
                  <div className="product">
                    <span><small>{strategy.product_id}</small><strong>{strategy.product_name}</strong></span>
                    <em><b>{strategy.risk_level}</b><strong>{(strategy.expected_return * 100).toFixed(2)}%</strong><small>预期年化</small></em>
                  </div>
                  <div className="strategy-meta">
                    <span><small>推荐渠道</small><b>{channelNames[strategy.recommended_channel]}</b></span>
                    <span><small>推荐时间</small><b>{strategy.recommended_time}</b></span>
                  </div>
                  <div className="reason">
                    <small>规则轨迹 · 个性化与合规性证据</small>
                    <ul className="rule-list">
                      {strategy.rule_trace.map((rule) => (
                        <li className={rule.passed ? "passed" : "failed"} key={rule.rule_id}>
                          <b>{rule.passed ? "✓" : "!"}</b><span>{rule.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  {failed.length > 0 && <p className="warn-text">存在{failed.length}项合规提示，执行前需复核。</p>}
                  <div className="script"><small>标准营销话术</small><p>{strategy.marketing_script}</p></div>
                  <div className="strategy-actions">
                    <Status warn={strategy.status === "待执行"}>{strategy.status}</Status>
                    <button onClick={() => { setTrackedStrategyId(strategy.strategy_id); setTab("track"); }}>执行该策略 →</button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {tab === "track" && (
        <div className="tracking">
          <section className="card">
            <div className="section-head"><div><h2>策略执行与响应归因</h2><p>事件采用append-only方式写入MySQL，可追溯、不覆盖。</p></div><Status>平台联动</Status></div>
            {strategies.length > 0 && (
              <label className="track-selector">
                当前策略
                <select value={trackedStrategy?.strategy_id ?? ""} onChange={(event) => setTrackedStrategyId(event.target.value)}>
                  {strategies.map((item) => <option key={item.strategy_id} value={item.strategy_id}>TOP{item.rank} · {item.product_id} · {item.status}</option>)}
                </select>
              </label>
            )}
            <div className="steps">
              {["策略生成", "已触达", "已响应"].map((label, index) => (
                <div className={trackedStrategy && (index === 0 || (index === 1 && trackedStrategy.status !== "待执行") || (index === 2 && trackedStrategy.status === "已响应")) ? "on" : ""} key={label}>
                  <i>{index + 1}</i><b>{index}</b><span>{label}</span>
                </div>
              ))}
            </div>
            {trackedStrategy ? (
              <div className="execution">
                <span className="avatar">{strategyCustomerId.slice(-2)}</span>
                <p><b>{strategyCustomerId} · {trackedStrategy.product_id} {trackedStrategy.product_name}</b><small>{channelNames[trackedStrategy.recommended_channel]} · {trackedStrategy.recommended_time}</small></p>
                <div>
                  <button disabled={busy || trackedStrategy.status !== "待执行"} onClick={() => void recordEvent({ event_type: "sent", strategy_id: trackedStrategy.strategy_id })}>✓ 标记已触达</button>
                  <button disabled={busy || trackedStrategy.status !== "已触达"} onClick={() => void recordEvent({ event_type: "responded", customer_id: strategyCustomerId, product_id: trackedStrategy.product_id, buy_date: "2026-04-20", amount: 50000 })}>记录窗口内响应</button>
                  <button className="secondary" disabled={busy || trackedStrategy.status !== "已响应"} onClick={() => void recordEvent({ event_type: "responded", customer_id: strategyCustomerId, product_id: trackedStrategy.product_id, buy_date: "2026-04-21", amount: 50000 })}>重复购买边界演示</button>
                </div>
              </div>
            ) : (
              <div className="empty-result"><b>请先加载一个客户的Top3策略</b></div>
            )}
          </section>
          <section className="card"><div className="section-head timeline-head"><h2>事件时间线</h2><Status>sent / responded</Status></div><Timeline items={timeline} /></section>
        </div>
      )}
    </>
  );
}
