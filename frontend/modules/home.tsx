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

/** 与看板一致的金额压缩格式（¥ 12.34亿 / ¥ 1,234.5万 / 全量） */
function compactMoney(value: number | null | undefined) {
  if (value == null) return "—";
  if (Math.abs(value) >= 100_000_000) {
    return `¥ ${(value / 100_000_000).toFixed(2)}亿`;
  }
  if (Math.abs(value) >= 10_000) {
    return `¥ ${(value / 10_000).toFixed(1)}万`;
  }
  return `¥ ${value.toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
  })}`;
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

  const goalText = encouragement(conversion?.gap, expiry?.customer_count);

  return (
    <div className="home-page">
      <section className="home-hero home-hero-full">
        <div className="home-greeting">
          <small>2026年4月15日 · 星期四 · 财富运营部</small>
          <h1>早上好，李经理</h1>
          <p>{goalText}</p>
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
            <p>{expiry.window_days} 天内 ¥{compactMoney(expiry.amount)} 到期；<b>{expiry.items[0]?.product_name ?? "—"}</b> 等产品迎来赎回，是挽留与再配置窗口</p>
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
          {business && <span><small>客户AUM</small><b>{compactMoney(business.total_aum)}</b></span>}
          {a1 && <span><small>模型AUC</small><b>{a1.auc?.toFixed(4) ?? "—"}</b></span>}
          {touch && <span><small>策略规模</small><b>{touch.total_strategies.toLocaleString()}</b></span>}
        </div>
      </section>

      {loading && <div className="home-loading">正在聚合今日数据…</div>}
      {error && <div className="home-error">{error}</div>}
    </div>
  );
}
