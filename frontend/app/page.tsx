"use client";

import { useState } from "react";

import { CustomerPage } from "../modules/customer";
import { DashboardPage } from "../modules/dashboard";
import { HomePage } from "../modules/home";
import { MarketingPage } from "../modules/marketing";
import { PortfolioPage } from "../modules/portfolio";

type Module = "home" | "customer" | "portfolio" | "marketing" | "dashboard";

const navigation: [Module, string, string, string][] = [
  ["home", "今", "今日工作台", "经理的一天与目标"],
  ["customer", "客", "客户进件与风险评估", "全景画像与风险证据"],
  ["portfolio", "投", "智能投顾推荐", "组合配置优化"],
  ["marketing", "营", "营销运营工作台", "响应预测与策略执行"],
  ["dashboard", "览", "可视化看板", "经营指标与算法证据"],
];

const titles: Record<Module, string> = {
  home: "今日工作台",
  customer: "客户进件与风险评估",
  portfolio: "智能投顾推荐",
  marketing: "营销运营工作台",
  dashboard: "可视化看板",
};

export default function Home() {
  const [active, setActive] = useState<Module>("home");
  const [customerId, setCustomerId] = useState("");
  const [marketingCohort, setMarketingCohort] = useState<"all" | "expiry">("all");
  const [toast, setToast] = useState("");

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 4000);
  }

  function openModule(module: Module) {
    setActive(module);
  }

  function openMarketing(nextCustomerId: string) {
    setCustomerId(nextCustomerId);
    setMarketingCohort("all");
    setActive("marketing");
  }

  function openMarketingWithCohort(
    nextCustomerId: string,
    cohort: "all" | "expiry"
  ) {
    setCustomerId(nextCustomerId);
    setMarketingCohort(cohort);
    setActive("marketing");
  }

  function openCustomer(nextCustomerId: string) {
    setCustomerId(nextCustomerId);
    setActive("customer");
  }

  function openPortfolio(nextCustomerId: string) {
    setCustomerId(nextCustomerId);
    setActive("portfolio");
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><b>兴</b><span><strong>智能财富管理</strong><small>运营平台</small></span></div>
        <nav>
          {navigation.map((item) => (
            <button key={item[0]} className={active === item[0] ? "on" : ""} onClick={() => setActive(item[0])}>
              <b>{item[1]}</b><span><strong>{item[2]}</strong><small>{item[3]}</small></span>
            </button>
          ))}
        </nav>
      </aside>

      <div className="main">
        <header>
          <div>智能财富管理运营平台 <i>›</i> <b>{titles[active]}</b></div>
          <section>
            <span><small>统一分析基准日</small><b>2026-03-31</b></span>
            <div className="user">李</div>
            <span><b>李经理</b><small>财富运营部</small></span>
          </section>
        </header>

        <main className={`page-${active}`}>
          {active === "home" && <HomePage onOpenModule={openModule} onOpenExpiry={(nextCustomerId) => openMarketingWithCohort(nextCustomerId, "expiry")} />}
          {active === "customer" && <CustomerPage initialCustomerId={customerId} onOpenMarketing={openMarketing} onOpenPortfolio={openPortfolio} notify={notify} />}
          {active === "portfolio" && <PortfolioPage initialCustomerId={customerId} notify={notify} onOpenMarketing={openMarketing} />}
          {active === "marketing" && <MarketingPage initialCustomerId={customerId} initialCohort={marketingCohort} onOpenCustomer={openCustomer} notify={notify} />}
          {active === "dashboard" && <DashboardPage onOpenMarketing={openMarketing} onOpenExpiry={(nextCustomerId) => openMarketingWithCohort(nextCustomerId, "expiry")} onOpenPortfolio={openPortfolio} />}
        </main>

        <footer>
          智能财富管理运营平台 · Competition Demo
          <span>A1预测 · A2策略 · Part B优化 · ODS/DWD/DWS/ADS</span>
        </footer>
      </div>

      {toast && (
        <div
          className="toast-box"
          role="button"
          tabIndex={0}
          onClick={() => setToast("")}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") setToast("");
          }}
        >
          <b>平台提示</b><p>{toast}</p>
        </div>
      )}
    </div>
  );
}
