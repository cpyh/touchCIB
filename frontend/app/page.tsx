"use client";

import { useState } from "react";

import { CustomerPage } from "../modules/customer";
import { DashboardPage } from "../modules/dashboard";
import { MarketingPage } from "../modules/marketing";
import { PortfolioPage } from "../modules/portfolio";

type Module = "customer" | "portfolio" | "marketing" | "dashboard";

const navigation: [Module, string, string, string][] = [
  ["customer", "客", "客户360", "画像与风险证据"],
  ["portfolio", "投", "智能投顾", "客户适配与组合优化"],
  ["marketing", "营", "营销运营", "响应预测与策略执行"],
  ["dashboard", "览", "Part C/D看板", "工程与运营闭环"],
];

const titles: Record<Module, string> = {
  customer: "客户360与风险画像",
  portfolio: "智能投顾组合配置优化",
  marketing: "精准营销运营工作台",
  dashboard: "Part C/D经营与工程看板",
};

export default function Home() {
  const [active, setActive] = useState<Module>("marketing");
  const [customerId, setCustomerId] = useState("");
  const [toast, setToast] = useState("");

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 4000);
  }

  function openMarketing(nextCustomerId: string) {
    setCustomerId(nextCustomerId);
    setActive("marketing");
  }

  function openCustomer(nextCustomerId: string) {
    setCustomerId(nextCustomerId);
    setActive("customer");
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
          {active === "customer" && <CustomerPage initialCustomerId={customerId} onOpenMarketing={openMarketing} notify={notify} />}
          {active === "portfolio" && <PortfolioPage initialCustomerId={customerId} notify={notify} />}
          {active === "marketing" && <MarketingPage initialCustomerId={customerId} onOpenCustomer={openCustomer} notify={notify} />}
          {active === "dashboard" && <DashboardPage notify={notify} />}
        </main>

        <footer>
          智能财富管理运营平台 · Competition Demo
          <span>A1预测 · A2策略 · Part B优化 · ODS/DWD/DWS/ADS</span>
        </footer>
      </div>

      {toast && (
        <div className="toast-box" onClick={() => setToast("")}>
          <b>平台提示</b><p>{toast}</p>
        </div>
      )}
    </div>
  );
}
