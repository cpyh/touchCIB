"use client";

import { useEffect, useState } from "react";

import { DashboardApiError, getDashboardOverview } from "../shared/dashboard-api";

type Module = "customer" | "portfolio" | "marketing" | "dashboard";

interface HomePageProps {
  onOpenModule: (module: Module) => void;
  onOpenExpiry: (customerId: string) => void;
}

const moduleEntries: Array<{
  module: Module;
  icon: string;
  title: string;
  note: string;
}> = [
  {
    module: "customer",
    icon: "客",
    title: "客户进件与风险评估",
    note: "全景画像 · AI 洞察 · 平台联动",
  },
  {
    module: "portfolio",
    icon: "投",
    title: "智能投顾推荐",
    note: "组合配置 · 最优性证书 · 配置缺口",
  },
  {
    module: "marketing",
    icon: "营",
    title: "营销运营工作台",
    note: "今日队列 · 策略执行 · 触达归因",
  },
  {
    module: "dashboard",
    icon: "览",
    title: "可视化看板",
    note: "目标缺口 · 到期预警 · 经营闭环",
  },
];

function encouragement(conversionGap: number | undefined, expiryCount: number | undefined) {
  if (conversionGap == null) return "今天也从看板开始，把目标拆成动作。";
  if (conversionGap <= 0) {
    return "四月转化目标已经达成，趁热打铁，继续经营到期资金。";
  }
  if (conversionGap <= 4) {
    return `转化目标还差 ${conversionGap} 个，今天拿下 ${conversionGap} 个就能提前达标。`;
  }
  return `转化目标还差 ${conversionGap} 个——把高意向客户排进今天的前三名。`;
}

export function HomePage({ onOpenModule, onOpenExpiry }: HomePageProps) {
  const [dashboard, setDashboard] = useState<Awaited<ReturnType<typeof getDashboardOverview>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getDashboardOverview("S01", controller.signal)
      .then(setDashboard)
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(requestError instanceof DashboardApiError ? requestError.message : "今日工作台加载失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const conversion = dashboard?.action_items?.conversion;
  const touch = dashboard?.action_items?.touch;
  const expiry = dashboard?.expiry_warning;
  const business = dashboard?.business_metrics;
  const a1 = dashboard?.a1_performance;

  const conversionRate = conversion && conversion.target > 0
    ? Math.min(1, conversion.actual / conversion.target)
    : 0;
  const goalText = encouragement(conversion?.gap, expiry?.customer_count);

  const goals = [
    {
      label: "四月经理转化",
      value: conversion ? `${conversion.actual}/${conversion.target}` : "—",
      note: conversion?.gap ? `还差 ${conversion.gap} 个` : "已达标",
      rate: conversionRate,
      module: "marketing" as Module,
    },
    {
      label: "到期跟进客户",
      value: expiry?.available ? `${expiry.customer_count}` : "—",
      note: "未来 30 天资金到期",
      rate: expiry?.customer_count ? Math.min(1, expiry.customer_count / 300) : 0,
      module: "marketing" as Module,
      expiry: true,
    },
    {
      label: "高意向未触达",
      value: touch ? touch.high_intent_untouched.toLocaleString() : "—",
      note: "概率 ≥70% 的待联系客户",
      rate: touch && touch.total_strategies ? Math.min(1, touch.high_intent_untouched / 1500) : 0,
      module: "marketing" as Module,
    },
  ];

  return (
    <div className="home-page">
      <section className="home-hero">
        <div className="home-greeting">
          <small>2026年4月15日 · 星期四 · 财富运营部</small>
          <h1>早上好，李经理</h1>
          <p>{goalText}</p>
          {expiry?.available && (
            <span className="home-expiry-hint">
              今天还有 {expiry.customer_count} 位客户的资金即将到期，记得安排跟进。
            </span>
          )}
        </div>
        <div className="home-goals">
          {goals.map((goal) => (
            <article
              className="home-goal-card"
              key={goal.label}
              onClick={() => {
                if (goal.expiry && expiry?.items[0]) {
                  onOpenExpiry(expiry.items[0].customer_id);
                } else {
                  onOpenModule(goal.module);
                }
              }}
            >
              <small>{goal.label}</small>
              <strong>{goal.value}</strong>
              <i><b style={{ width: `${goal.rate * 100}%` }} /></i>
              <span>{goal.note}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="home-modules">
        {moduleEntries.map((entry) => (
          <button className="home-module-card" key={entry.module} onClick={() => onOpenModule(entry.module)}>
            <b>{entry.icon}</b>
            <span>
              <strong>{entry.title}</strong>
              <small>{entry.note}</small>
            </span>
            <em>→</em>
          </button>
        ))}
      </section>

      <section className="home-today-strip">
        <div>
          <b>今日建议</b>
          {conversion && conversion.gap > 0 ? (
            <span>优先跟进 {conversion.gap > 1 ? `${conversion.gap} 位` : "1 位"}已触达未响应的客户，把转化进度往上推一格。</span>
          ) : (
            <span>目标已达成，把精力转到到期资金再配置上。</span>
          )}
          <button className="primary" onClick={() => onOpenModule("marketing")}>去营销工作台 →</button>
        </div>
        <div className="home-snapshot">
          {business && <span><small>客户总数</small><b>{business.customer_count.toLocaleString()}</b></span>}
          {business && <span><small>客户AUM</small><b>¥{business.total_aum >= 1e8 ? `${(business.total_aum / 1e8).toFixed(1)}亿` : `${Math.round(business.total_aum / 1e4).toLocaleString()}万`}</b></span>}
          {a1 && <span><small>模型AUC</small><b>{a1.auc?.toFixed(4) ?? "—"}</b></span>}
          {touch && <span><small>策略规模</small><b>{touch.total_strategies.toLocaleString()}</b></span>}
        </div>
      </section>

      {loading && <div className="home-loading">正在聚合今日数据…</div>}
      {error && <div className="home-error">{error}</div>}
    </div>
  );
}
