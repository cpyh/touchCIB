"use client";

import { useEffect, useState } from "react";

import { DashboardApiError, getDashboardOverview } from "../shared/dashboard-api";
import { compactMoney } from "../shared/format";

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

  const goalText = encouragement(conversion?.gap, expiry?.customer_count);
  const fortune = (() => {
    if (conversion == null) return { emoji: "🪙", text: "数据加载中…" };
    if (conversion.gap <= 0) {
      return { emoji: "🎉", text: "今日宜庆祝：转化目标已达成" };
    }
    if (conversion.gap <= 4) {
      return { emoji: "🪙", text: `今日宜冲刺：再拿下 ${conversion.gap} 个即可达标` };
    }
    if (expiry?.customer_count) {
      return { emoji: "💛", text: "今日宜经营：到期资金是好运名单" };
    }
    return { emoji: "📞", text: "今日宜联系：高意向客户优先" };
  })();

  return (
    <div className="home-page">
      <section className="home-hero home-hero-compact">
        <div className="home-greeting">
          <small>2026年4月15日 · 星期四 · 财富运营部</small>
          <h1>早上好，李经理</h1>
          <p>{goalText}</p>
        </div>
        <div className="home-hero-side">
          <span className="home-advice">
            {conversion && conversion.gap > 0
              ? `今日建议：优先跟进已触达未响应的客户，转化进度往上推一格。`
              : "今日建议：目标已达成，把精力转到到期资金再配置上。"}
          </span>
          <button className="primary" onClick={() => onOpenModule("marketing")}>去营销工作台 →</button>
          <div className="home-mascot">
            <i>兴</i>
            <span><em>{fortune.emoji}</em><b>{fortune.text}</b></span>
          </div>
          <div className="home-snapshot">
            {business && <span><small>客户</small><b>{business.customer_count.toLocaleString()}</b></span>}
            {business && <span><small>AUM</small><b>{compactMoney(business.total_aum)}</b></span>}
          </div>
        </div>
      </section>

      <section className="home-actions">
        <article className={`action-card ${(conversion?.gap ?? 0) > 0 ? "level-red" : "level-green"}`}>
          <header><b>转化缺口</b><span>{conversion?.gap ? `还差 ${conversion.gap} 个` : "已达目标"}</span></header>
          <strong>{conversion?.actual ?? "—"}<i>/</i><em>{conversion?.target ?? "—"}</em></strong>
          <p>{conversion?.label ?? "经理 4月转化"} · 已触达未响应的客户是跟进的优先对象</p>
          <button className="primary" onClick={() => onOpenModule("marketing")}>去营销工作台执行 →</button>
        </article>

        <article className={`action-card ${(touch?.sent_customers ?? 0) < (touch?.total_customers ?? 1) ? "level-amber" : "level-green"}`}>
          <header><b>触达缺口</b><span>{(touch?.total_customers ?? 0) - (touch?.sent_customers ?? 0)} 位客户待触达</span></header>
          <strong>{touch?.sent_customers?.toLocaleString() ?? "—"}<i>/</i><em>{touch?.total_customers?.toLocaleString() ?? "—"}</em></strong>
          <p>高意向客户（概率≥70%）中还有 <b>{touch?.high_intent_untouched ?? "—"}</b> 名未触达，建议今日优先执行</p>
          <button className="primary" onClick={() => onOpenModule("marketing")}>优先触达高意向客户 →</button>
        </article>

        {expiry?.available && (
          <article className="action-card level-amber">
            <header><b>到期跟进</b><span>再配置机会</span></header>
            <strong>{expiry.holding_count.toLocaleString()}<i>笔</i><em>{expiry.customer_count.toLocaleString()} 位客户</em></strong>
            <p>{expiry.window_days} 天内 ¥{compactMoney(expiry.amount)} 到期，是挽留与再配置窗口</p>
            <button
              className="primary"
              onClick={() => onOpenExpiry(expiry.items[0]?.customer_id ?? "")}
            >
              跟进到期客户 →
            </button>
          </article>
        )}
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

      {loading && <div className="home-loading">正在聚合今日数据…</div>}
      {error && <div className="home-error">{error}</div>}
    </div>
  );
}
