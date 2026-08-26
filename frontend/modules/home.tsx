"use client";

import { useEffect, useState } from "react";

import { DashboardApiError, getDashboardOverview } from "../shared/dashboard-api";
import { compactMoney, formatNumber } from "../shared/format";

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

function encouragement(conversionGap: number | undefined) {
  if (conversionGap == null) return "今天也从看板开始，把目标拆成动作。";
  if (conversionGap <= 0) {
    return "四月转化目标已经达成，趁热打铁，继续经营到期资金。";
  }
  if (conversionGap <= 4) {
    return `转化目标还差 ${formatNumber(conversionGap)} 个，今天拿下 ${formatNumber(conversionGap)} 个就能提前达标。`;
  }
  return `转化目标还差 ${formatNumber(conversionGap)} 个——把高意向客户排进今天的前三名。`;
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

  const goalText = encouragement(conversion?.gap);
  return (
    <div className="home-page">
      <section className="home-hero home-hero-compact">
        <div className="home-greeting">
          <small>2026年4月15日 · 星期四 · 财富运营部</small>
          <h1>早上好，李经理</h1>
          <p>{goalText}</p>
        </div>
        <div className="home-hero-side">
          <div className="home-snapshot">
            {business && <span><small>服务客户</small><b>{formatNumber(business.customer_count)}</b></span>}
            {business && <span><small>管理 AUM</small><b>{compactMoney(business.total_aum)}</b></span>}
          </div>
          <div className="home-focus">
            <small>今日经营重点</small>
            <strong>
              {conversion && conversion.gap > 0
                ? "优先跟进已触达未响应客户"
                : "经营到期资金再配置机会"}
            </strong>
            <span>{conversion?.gap ? `本月目标还差 ${formatNumber(conversion.gap)} 个转化` : "本月目标已达成"}</span>
          </div>
          <button className="home-hero-action" onClick={() => onOpenModule("marketing")}><span>开始今日跟进</span><i>→</i></button>
        </div>
      </section>

      <div className="home-workspace">
        <section className="home-priority-panel">
          <header className="home-panel-head">
            <div><small>今日待办</small><h2>优先处理这三类客户</h2></div>
            <span>按机会与时效排序</span>
          </header>
          <div className="home-actions">
            <article className={`action-card ${(conversion?.gap ?? 0) > 0 ? "level-red" : "level-green"}`}>
              <small className="home-action-kicker">01 · 转化推进</small>
              <header><b>本月转化缺口</b><span>{conversion?.gap ? `还差 ${formatNumber(conversion.gap)} 个` : "已达目标"}</span></header>
              <strong>{formatNumber(conversion?.actual)}<i>/</i><em>{formatNumber(conversion?.target)}</em></strong>
              <p>{conversion?.label ?? "经理 4月转化"} · 优先跟进已触达未响应客户</p>
              <button className="primary" onClick={() => onOpenModule("marketing")}>开始转化跟进 <i>→</i></button>
            </article>

            <article className={`action-card ${(touch?.sent_customers ?? 0) < (touch?.total_customers ?? 1) ? "level-amber" : "level-green"}`}>
              <small className="home-action-kicker">02 · 高意向触达</small>
              <header><b>客户触达缺口</b><span>{formatNumber((touch?.total_customers ?? 0) - (touch?.sent_customers ?? 0))} 人待触达</span></header>
              <strong>{formatNumber(touch?.sent_customers)}<i>/</i><em>{formatNumber(touch?.total_customers)}</em></strong>
              <p>概率 ≥ 70% 的客户中，还有 <b>{formatNumber(touch?.high_intent_untouched)}</b> 名未触达</p>
              <button className="primary" onClick={() => onOpenModule("marketing")}>查看高意向客户 <i>→</i></button>
            </article>

            {expiry?.available && (
              <article className="action-card level-amber">
                <small className="home-action-kicker">03 · 到期经营</small>
                <header><b>资金到期跟进</b><span>再配置机会</span></header>
                <strong>{formatNumber(expiry.holding_count)}<i>笔</i><em>{formatNumber(expiry.customer_count)} 位客户</em></strong>
                <p>{formatNumber(expiry.window_days)} 天内 {compactMoney(expiry.amount)} 到期，建议提前完成再配置沟通</p>
                <button className="primary" onClick={() => onOpenExpiry(expiry.items[0]?.customer_id ?? "")}>进入到期名单 <i>→</i></button>
              </article>
            )}
          </div>
        </section>

        <section className="home-module-panel">
          <header className="home-panel-head">
            <div><small>快捷入口</small><h2>业务能力</h2></div>
            <span>四个工作场景</span>
          </header>
          <div className="home-modules">
            {moduleEntries.map((entry) => (
              <button className="home-module-card" key={entry.module} onClick={() => onOpenModule(entry.module)}>
                <b>{entry.icon}</b>
                <span><strong>{entry.title}</strong><small>{entry.note}</small></span>
                <em>→</em>
              </button>
            ))}
          </div>
        </section>
      </div>

      {loading && <div className="home-loading">正在聚合今日数据…</div>}
      {error && <div className="home-error">{error}</div>}
    </div>
  );
}
