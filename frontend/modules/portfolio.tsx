"use client";

import { useEffect, useMemo, useState } from "react";

import { api, API_BASE } from "../shared/api";
import { formatNumber, metric, money, percent } from "../shared/format";
import { Metric, Status, riskNames } from "../shared/ui";

interface Scenario {
  scenario_id: string;
  scenario_name: string;
  scenario_type: "preset" | "custom";
  total_amount: number;
  risk_aversion: number;
  max_single_weight: number;
  max_high_risk_weight: number;
  min_liquid_weight: number;
  min_holdings: number;
}

interface Allocation {
  product_id: string;
  product_name: string;
  risk_level: string;
  liquidity: string;
  weight: number;
  amount: number;
}

interface PortfolioResult {
  scenario: Record<string, number>;
  summary: {
    utility: number;
    expected_return: number;
    portfolio_volatility: number;
    invested_weight: number;
    cash_weight: number;
    holdings_count: number;
    high_risk_weight: number;
    liquid_plus_cash: number;
    optimality_gap: number;
  };
  allocations: Allocation[];
  business?: {
    utility: number;
    retention_ratio: number | null;
    expected_return: number;
    portfolio_volatility: number;
    cash_weight: number;
    cash_amount: number;
    holdings_count: number;
    high_risk_weight: number;
    liquid_plus_cash: number;
    allocations: Array<{
      product_id: string;
      product_name: string;
      min_invest: number;
      weight: number;
      amount: number;
    }>;
  };
}

interface CustomerProfile {
  customer_id: string;
  aum: number;
  risk_appetite: string;
  vip_level: string;
}

interface RiskDefaults {
  riskAversion: number;
  maxHighRiskWeight: number;
}

const riskDefaults: Record<string, RiskDefaults> = {
  R1: { riskAversion: 2.9, maxHighRiskWeight: 0 },
  R2: { riskAversion: 2.2, maxHighRiskWeight: 0.1 },
  R3: { riskAversion: 1.5, maxHighRiskWeight: 0.3 },
  R4: { riskAversion: 0.9, maxHighRiskWeight: 0.5 },
  R5: { riskAversion: 0.6, maxHighRiskWeight: 0.7 },
};

interface SliderControlProps {
  label: string;
  note: string;
  min: number;
  max: number;
  step: number;
  inputStep?: number;
  unit?: string;
  value: number;
  onChange: (value: number) => void;
}

function SliderControl(props: SliderControlProps) {
  return (
    <label className="constraint-control">
      <span>
        <b>{props.label}</b>
        <span className="constraint-number">
          <input
            aria-label={`${props.label}精确值`}
            type="number"
            min={props.min}
            max={props.max}
            step={props.inputStep ?? props.step}
            value={props.value}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value)) props.onChange(value);
            }}
          />
          {props.unit && <i>{props.unit}</i>}
        </span>
      </span>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        onChange={(event) => props.onChange(Number(event.target.value))}
      />
      <small>{props.note}</small>
    </label>
  );
}

const allocationColors = ["#123f6b", "#286b9f", "#5a91b8", "#d39b36", "#7b8fa3", "#b6c2cc", "#e1e7ec"];

export function PortfolioPage({
  businessDate,
  initialCustomerId,
  notify,
  onOpenMarketing,
}: {
  businessDate: string;
  initialCustomerId?: string;
  notify: (message: string) => void;
  onOpenMarketing?: (customerId: string) => void;
}) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("S01");
  const [totalAmount, setTotalAmount] = useState(500000);
  const [riskAversion, setRiskAversion] = useState(0.94);
  const [maxSingleWeight, setMaxSingleWeight] = useState(0.3);
  const [maxHighRiskWeight, setMaxHighRiskWeight] = useState(0.5);
  const [minLiquidWeight, setMinLiquidWeight] = useState(0.2);
  const [minHoldings, setMinHoldings] = useState(4);
  const [result, setResult] = useState<PortfolioResult | null>(null);
  const [resultView, setResultView] = useState<"overview" | "business" | "detail" | "guards" | "ai">("overview");
  const [busy, setBusy] = useState(false);
  const [customerQuery, setCustomerQuery] = useState(initialCustomerId || "C000001");
  const [customer, setCustomer] = useState<CustomerProfile | null>(null);
  const [customerBusy, setCustomerBusy] = useState(false);
  const [parameterSource, setParameterSource] = useState<"scenario" | "customer" | "manual">("scenario");
  const [rebalance, setRebalance] = useState<{
    buys: Array<{ product_id: string; product_name: string; amount: number }>;
    sells: Array<{ product_id: string; product_name: string; amount: number }>;
  } | null>(null);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

  useEffect(() => {
    api<{ scenarios: Scenario[] }>("/portfolio/scenarios")
      .then((data) => {
        setScenarios(data.scenarios);
        const first = data.scenarios.find((item) => item.scenario_id === "S01") ?? data.scenarios[0];
        // 从客户页跳转进入时不覆盖按画像自动生成的参数
        if (first && !initialCustomerId) applyScenario(first);
      })
      .catch((error) => notify(`投资场景加载失败：${error.message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const target = initialCustomerId?.trim().toUpperCase() || "C000001";
    void loadCustomer(target, false).then((profile) => {
      // 从客户画像页跳转而来（带客户 ID）时自动按画像生成默认约束
      if (profile && initialCustomerId) applyCustomerRisk(profile);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCustomerId]);

  useEffect(() => {
    if (!customer || !result?.business) return;
    let cancelled = false;
    api<{
      code: number;
      data: {
        asset_profile?: {
          holdings?: Array<{
            product_id: string;
            product_name: string;
            amount: number;
          }>;
        };
      } | null;
    }>(`/api/v1/customers/${customer.customer_id}/profile`)
      .then((envelope) => {
        if (cancelled) return;
        const holdings = envelope.data?.asset_profile?.holdings ?? [];
        const held = new Map(holdings.map((item) => [item.product_id, item]));
        const buys = result.business!.allocations
          .filter((item) => !held.has(item.product_id))
          .slice(0, 3)
          .map((item) => ({
            product_id: item.product_id,
            product_name: item.product_name,
            amount: item.amount,
          }));
        const sells = holdings
          .filter(
            (item) =>
              !result.business!.allocations.some(
                (allocation) => allocation.product_id === item.product_id
              )
          )
          .sort((left, right) => right.amount - left.amount)
          .slice(0, 3)
          .map((item) => ({
            product_id: item.product_id,
            product_name: item.product_name,
            amount: item.amount,
          }));
        if (!cancelled) setRebalance({ buys, sells });
      })
      .catch(() => {
        if (!cancelled) setRebalance(null);
      });
    return () => {
      cancelled = true;
    };
  }, [customer, result]);

  const selectedScenario = useMemo(
    () => scenarios.find((item) => item.scenario_id === scenarioId),
    [scenarioId, scenarios],
  );
  const officialCount = scenarios.filter((item) => item.scenario_type === "preset").length;

  const isCustomized = Boolean(selectedScenario) && (
    totalAmount !== Number(selectedScenario?.total_amount) ||
    Math.abs(riskAversion - Number(selectedScenario?.risk_aversion)) > 1e-9 ||
    Math.abs(maxSingleWeight - Number(selectedScenario?.max_single_weight)) > 1e-9 ||
    Math.abs(maxHighRiskWeight - Number(selectedScenario?.max_high_risk_weight)) > 1e-9 ||
    Math.abs(minLiquidWeight - Number(selectedScenario?.min_liquid_weight)) > 1e-9 ||
    minHoldings !== Number(selectedScenario?.min_holdings)
  );

  function applyScenario(scenario: Scenario) {
    setScenarioId(scenario.scenario_id);
    setTotalAmount(Number(scenario.total_amount));
    setRiskAversion(Number(scenario.risk_aversion));
    setMaxSingleWeight(Number(scenario.max_single_weight));
    setMaxHighRiskWeight(Number(scenario.max_high_risk_weight));
    setMinLiquidWeight(Number(scenario.min_liquid_weight));
    setMinHoldings(Number(scenario.min_holdings));
    setResult(null);
    setResultView("overview");
    setParameterSource("scenario");
  }

  function chooseScenario(nextId: string) {
    const scenario = scenarios.find((item) => item.scenario_id === nextId);
    if (scenario) applyScenario(scenario);
  }

  function changeConstraint(action: () => void) {
    action();
    setResult(null);
    setParameterSource("manual");
  }

  async function loadCustomer(customerId: string, announce = true): Promise<CustomerProfile | null> {
    const normalized = customerId.trim().toUpperCase();
    if (!normalized) {
      notify("请输入客户编号");
      return null;
    }
    setCustomerBusy(true);
    setRebalance(null);
    try {
      const data = await api<CustomerProfile>(
        `/customers/${encodeURIComponent(normalized)}/profile?business_date=${encodeURIComponent(businessDate)}`,
      );
      setCustomer(data);
      setCustomerQuery(normalized);
      if (announce) notify(`已加载客户 ${normalized} 的风险画像`);
      return data;
    } catch (error) {
      notify(`客户画像加载失败：${(error as Error).message}`);
      return null;
    } finally {
      setCustomerBusy(false);
    }
  }

  function applyCustomerRisk(profile?: CustomerProfile) {
    const source = profile ?? customer;
    if (!source) return;
    const defaults = riskDefaults[source.risk_appetite];
    if (!defaults) {
      notify(`无法识别风险等级 ${source.risk_appetite}`);
      return;
    }
    setRiskAversion(defaults.riskAversion);
    setMaxHighRiskWeight(defaults.maxHighRiskWeight);
    setTotalAmount(source.aum);
    setMaxSingleWeight(0.3);
    setMinLiquidWeight(0.2);
    setMinHoldings(4);
    setResult(null);
    setResultView("overview");
    setParameterSource("customer");
    notify(`已按 ${source.risk_appetite} ${riskNames[source.risk_appetite]}与客户 AUM 自动生成默认方案`);
  }

  async function optimize() {
    setBusy(true);
    setRebalance(null);
    try {
      const data = await api<PortfolioResult>("/portfolio/optimize", {
        method: "POST",
        body: JSON.stringify({
          total_amount: totalAmount,
          risk_aversion: riskAversion,
          max_single_weight: maxSingleWeight,
          max_high_risk_weight: maxHighRiskWeight,
          min_liquid_weight: minLiquidWeight,
          min_holdings: minHoldings,
        }),
      });
      setResult(data);
      setResultView("overview");
      setChatMessages([]);
    } catch (error) {
      notify(`组合优化失败：${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  function chatContext() {
    return {
      customer: customer ? { risk_appetite: customer.risk_appetite, aum: customer.aum } : null,
      summary: result?.summary ?? null,
      business: result?.business ?? null,
      buys: rebalance?.buys ?? [],
      sells: rebalance?.sells ?? [],
    };
  }

  async function sendChat(text: string) {
    const content = text.trim();
    if (!content || chatBusy) return;
    const history = [...chatMessages, { role: "user" as const, content }];
    setChatMessages([...history, { role: "assistant", content: "" }]);
    setChatInput("");
    setChatBusy(true);
    try {
      const response = await fetch(`${API_BASE}/portfolio/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: chatContext(), messages: history }),
      });
      const reader = response.body?.getReader();
      if (!reader) throw new Error("浏览器不支持流式读取");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let split;
        while ((split = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          for (const line of raw.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const data = JSON.parse(line.slice(6));
            if (data.delta) {
              setChatMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  next[next.length - 1] = { ...last, content: last.content + data.delta };
                }
                return next;
              });
            } else if (data.error) {
              notify(`AI 回复失败：${data.error}`);
            }
          }
        }
      }
    } catch (error) {
      notify(`AI 对话失败：${(error as Error).message}`);
    } finally {
      setChatBusy(false);
    }
  }

  const summary = result?.summary;
  const allocations = result?.allocations ?? [];
  const maxWeight = allocations.reduce((current, item) => Math.max(current, item.weight), 0);
  const guards = summary && result
    ? [
        { name: "总仓位", rule: "产品合计 ≤ 100%", actual: percent(summary.invested_weight), passed: summary.invested_weight <= 1.000001 },
        { name: "单品上限", rule: `不超过 ${percent(result.scenario.max_single_weight, 0)}`, actual: percent(maxWeight), passed: maxWeight <= result.scenario.max_single_weight + 1e-6 },
        { name: "高风险仓位", rule: `不超过 ${percent(result.scenario.max_high_risk_weight, 0)}`, actual: percent(summary.high_risk_weight), passed: summary.high_risk_weight <= result.scenario.max_high_risk_weight + 1e-6 },
        { name: "流动性", rule: `至少 ${percent(result.scenario.min_liquid_weight, 0)}`, actual: percent(summary.liquid_plus_cash), passed: summary.liquid_plus_cash >= result.scenario.min_liquid_weight - 1e-6 },
        { name: "分散度", rule: `至少 ${formatNumber(result.scenario.min_holdings)} 款`, actual: `${formatNumber(summary.holdings_count)} 款`, passed: summary.holdings_count >= result.scenario.min_holdings },
      ]
    : [];
  const allPassed = guards.length > 0 && guards.every((item) => item.passed);

  const topAllocations = allocations.slice(0, 5);
  const topWeight = topAllocations.reduce((total, item) => total + item.weight, 0);
  const otherWeight = Math.max(0, (summary?.invested_weight ?? 0) - topWeight);
  const distribution = [
    ...topAllocations.map((item) => ({ label: item.product_name, weight: item.weight })),
    ...(otherWeight >= 1e-6 ? [{ label: "其他产品", weight: otherWeight }] : []),
    ...((summary?.cash_weight ?? 0) >= 1e-6 ? [{ label: "现金", weight: summary?.cash_weight ?? 0 }] : []),
  ];
  const parameterStatus = parameterSource === "customer" && customer
    ? `${customer.risk_appetite}客户参数`
    : isCustomized
      ? "已调整官方参数"
      : "使用官方参数";
  const isDerivedScenario = parameterSource !== "scenario";
  const derivedScenarioLabel = parameterSource === "customer" && customer
    ? `客户定制 · ${customer.customer_id}`
    : "自定义参数";
  const activeScenarioLabel = isDerivedScenario
    ? derivedScenarioLabel
    : `${scenarioId}场景`;

  return (
    <>
      <section className="portfolio-hero">
        <div className="portfolio-hero-copy">
          <span>智能投顾 · 投资组合优化</span>
          <h1>智能投顾推荐</h1>
          <p>选择客户与投资场景，调整约束并实时生成可解释的近优组合。</p>
          <div className="portfolio-hero-tags"><i>{formatNumber(officialCount || 20)} 个场景</i><i>30 个产品</i><i>5 类硬约束</i></div>
          <div className="portfolio-client-link">
            <span>当前客户</span>
            <input
              aria-label="智能投顾客户编号"
              value={customerQuery}
              onChange={(event) => setCustomerQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void loadCustomer(customerQuery);
              }}
            />
            <button disabled={customerBusy} onClick={() => void loadCustomer(customerQuery)}>
              {customerBusy ? "加载中" : "加载画像"}
            </button>
            {customer ? (
              <div className="portfolio-client-profile">
                <b>{customer.customer_id}</b>
                <i>{customer.risk_appetite} · {riskNames[customer.risk_appetite]}</i>
                <small>{customer.vip_level} · AUM {money(customer.aum)}</small>
                <button onClick={() => applyCustomerRisk()}>应用{customer.risk_appetite}参数</button>
              </div>
            ) : <small>加载画像后可按风险偏好生成默认约束</small>}
          </div>
        </div>
        <div className="scenario-quick-panel">
          <label>选择投资场景
            <select value={isDerivedScenario ? "__derived__" : scenarioId} onChange={(event) => chooseScenario(event.target.value)}>
              {isDerivedScenario && <option value="__derived__" disabled>{derivedScenarioLabel}</option>}
              {scenarios.map((scenario) => (
                <option key={scenario.scenario_id} value={scenario.scenario_id}>
                  {scenario.scenario_id} · {scenario.scenario_name}{scenario.scenario_type === "custom" ? "（自定义）" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>可配置资金
            <div className="amount-input"><span>¥</span><input type="number" min="10000" step="10000" value={totalAmount} onChange={(event) => changeConstraint(() => setTotalAmount(Number(event.target.value)))} /></div>
          </label>
          <div className="scenario-state">
            <Status warn={parameterSource !== "scenario" || isCustomized}>{parameterStatus}</Status>
            <button disabled={!selectedScenario || (!isCustomized && parameterSource === "scenario")} onClick={() => selectedScenario && applyScenario(selectedScenario)}>恢复官方值</button>
          </div>
        </div>
      </section>

      <nav className="portfolio-story" aria-label="投顾叙事进度">
        {[
          ["客户画像", customer != null],
          ["理论最优", !!summary],
          ["业务可执行", !!result?.business],
          ["落地执行", !!rebalance],
        ].map(([label, done], index) => (
          <span key={label as string} className={done ? "on" : ""}>
            <i>{index + 1}</i>
            <b>{label as string}</b>
            {index < 3 && <em>→</em>}
          </span>
        ))}
      </nav>

      <div className="investment-workbench">
        <aside className="card constraint-panel">
          <div className="section-head"><div><h2>约束控制台</h2><p>修改任一参数后重新生成方案</p></div><span className="engine-live"><i />求解器在线</span></div>
          <div className="constraint-page">
            <SliderControl
              label="风险厌恶系数 λ"
              note="越高越重视控制波动"
              min={0.1} max={3} step={0.1} inputStep={0.01} value={riskAversion}
              onChange={(value) => changeConstraint(() => setRiskAversion(value))}
            />
            <SliderControl
              label="单产品权重上限"
              note="控制单一产品集中度"
              min={5} max={50} step={5} inputStep={1} unit="%" value={maxSingleWeight * 100}
              onChange={(value) => changeConstraint(() => setMaxSingleWeight(value / 100))}
            />
            <SliderControl
              label="R4/R5仓位上限"
              note="限制高风险产品总比例"
              min={0} max={100} step={5} inputStep={1} unit="%" value={maxHighRiskWeight * 100}
              onChange={(value) => changeConstraint(() => setMaxHighRiskWeight(value / 100))}
            />
            <SliderControl
              label="最低流动资产比例"
              note="T+0、T+1与现金共同计入"
              min={0} max={100} step={5} inputStep={1} unit="%" value={minLiquidWeight * 100}
              onChange={(value) => changeConstraint(() => setMinLiquidWeight(value / 100))}
            />
            <SliderControl
              label="最低持仓产品数"
              note="权重达到1e-6才计入"
              min={1} max={30} step={1} unit="款" value={minHoldings}
              onChange={(value) => changeConstraint(() => setMinHoldings(Math.round(value)))}
            />
          </div>
          <div className="constraint-actions">
            <button className="primary full optimize-button" disabled={busy || totalAmount <= 0} onClick={() => void optimize()}>
              {busy ? "优化器正在计算…" : "生成最优配置方案"}
            </button>
            <p className="solver-note">随机种子42 · 按1e-6容差复验硬约束</p>
          </div>
        </aside>

        <main className="portfolio-result-area">
          {!summary && (
            <section className="card optimization-placeholder">
              <div className="formula-mark">U = r − λσ</div>
              <h2>配置方案等待生成</h2>
              <p>先在左侧调整投资约束，再运行优化器。结果区将展示组合指标、资产分布、产品明细与约束检查。</p>
              <div><span>30</span>产品池<i /> <span>5</span>硬约束<i /> <span>1</span>近优方案</div>
            </section>
          )}

          {summary && (
            <section className="card portfolio-overview">
              <div className="result-toolbar">
                <div><h2>组合驾驶舱</h2><p>{activeScenarioLabel} · 配置金额 {money(totalAmount)}</p></div>
                <div className="result-tabs">
                  <button className={resultView === "overview" ? "on" : ""} onClick={() => setResultView("overview")}>组合概览</button>
                  <button className={resultView === "business" ? "on" : ""} onClick={() => setResultView("business")}>业务落地</button>
                  <button className={resultView === "detail" ? "on" : ""} onClick={() => setResultView("detail")}>产品明细</button>
                  <button className={resultView === "guards" ? "on" : ""} onClick={() => setResultView("guards")}>合规校验</button>
                  <button className={resultView === "ai" ? "on" : ""} onClick={() => {
                    setResultView("ai");
                    if (result && chatMessages.length === 0 && !chatBusy) {
                      void sendChat("帮我解读这个组合方案");
                    }
                  }}>AI分析</button>
                </div>
                <Status warn={!allPassed}>{allPassed ? "全部约束通过" : "存在约束违例"}</Status>
              </div>

              {resultView === "overview" && (
                <div className="result-view">
                  <div className="metrics">
                    <Metric label="预期年化收益" value={percent(summary.expected_return, 2)} note="组合加权收益" gold />
                    <Metric label="组合波动率" value={percent(summary.portfolio_volatility, 2)} note="相关矩阵计算" />
                    <Metric label="组合效用 U" value={metric(summary.utility, 4)} note="Part B核心目标" />
                    <Metric label="最优性 gap" value={summary.optimality_gap.toExponential(1)} note="接近0表示近优" />
                  </div>

                  <div className="allocation-visual">
                    <div className="allocation-visual-head"><span><b>资产配置分布</b><small>{formatNumber(summary.holdings_count)} 款产品 + 现金仓位</small></span><strong>{percent(summary.invested_weight)}<small>已投资</small></strong></div>
                    <div className="allocation-stack">
                      {distribution.map((item, index) => <i key={item.label} title={`${item.label} ${percent(item.weight)}`} style={{ width: `${item.weight * 100}%`, background: allocationColors[index % allocationColors.length] }} />)}
                    </div>
                    <div className="allocation-legend">
                      {distribution.map((item, index) => <span key={item.label}><i style={{ background: allocationColors[index % allocationColors.length] }} /><b>{item.label}</b><em>{percent(item.weight)}</em></span>)}
                    </div>
                  </div>

                  {result?.business && (
                    <div className="theory-business-bridge">
                      <div className="bridge-side">
                        <small>理论最优方案</small>
                        <b>{formatNumber(summary.holdings_count)} 款产品</b>
                        <span>收益 {percent(summary.expected_return, 2)} · 现金 {percent(summary.cash_weight)}</span>
                      </div>
                      <div className="bridge-core">
                        <em>业务保真率</em>
                        <strong>{percent(result.business.retention_ratio)}</strong>
                        <button className="secondary" onClick={() => setResultView("business")}>查看业务落地明细 →</button>
                      </div>
                      <div className="bridge-side">
                        <small>业务可执行方案</small>
                        <b>{formatNumber(result.business.holdings_count)} 款产品</b>
                        <span>收益 {percent(result.business.expected_return, 2)} · 现金 {percent(result.business.cash_weight)}</span>
                      </div>
                    </div>
                  )}

                </div>
              )}

              {resultView === "guards" && (
                <div className="result-view guard-page">
                  <div className="guard-section-inline">
                    <div className="section-head"><div><h2>约束守卫</h2><p>方案写出前按赛事口径逐项独立校验</p></div><Status>{guards.filter((item) => item.passed).length}/{guards.length}通过</Status></div>
                    <div className="guard-grid">
                      {guards.map((guard) => (
                        <div className={guard.passed ? "passed" : "failed"} key={guard.name}>
                          <b>{guard.passed ? "✓" : "!"}</b>
                          <span><strong>{guard.name}</strong><small>{guard.rule}</small></span>
                          <em>{guard.actual}</em>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {resultView === "ai" && (
                <div className="result-view portfolio-ai-page portfolio-chat">
                  <div className="chat-head">
                    <div className="portfolio-ai-mark">AI</div>
                    <span><small>AI 投顾助手</small><h3>组合方案问答</h3></span>
                    <Status>{chatBusy ? "回复中" : "DeepSeek"}</Status>
                  </div>
                  <div className="chat-body">
                    {chatMessages.map((message, index) => (
                      <div key={index} className={`chat-row chat-${message.role}`}>
                        <div className="chat-bubble">
                          {message.content}{chatBusy && index === chatMessages.length - 1 && message.role === "assistant" ? "▍" : ""}
                        </div>
                      </div>
                    ))}
                    {chatMessages.length === 0 && !chatBusy && (
                      <div className="chat-empty">生成方案后，AI 会自动解读；你也可以随时追问。</div>
                    )}
                  </div>
                  <div className="chat-foot">
                    <input
                      aria-label="向 AI 投顾助手提问"
                      placeholder="追问：为什么选这个产品？风险改 R4 会怎样？"
                      value={chatInput}
                      onChange={(event) => setChatInput(event.target.value)}
                      onKeyDown={(event) => { if (event.key === "Enter" && !chatBusy) void sendChat(chatInput); }}
                    />
                    <button className="primary" disabled={chatBusy || !chatInput.trim()} onClick={() => void sendChat(chatInput)}>发送</button>
                  </div>
                  <div className="portfolio-ai-trace">
                    <p>AI 回复基于当前方案上下文，不替代客户适当性、产品准入和起投金额校验。</p>
                  </div>
                </div>
              )}
              {resultView === "business" && (
                <div className="result-view business-view">
                  {result?.business ? (
                    <>
                      <div className="business-metrics">
                        <Metric label="业务保真率" value={percent(result.business.retention_ratio)} note="业务效用 ÷ 理论效用" gold />
                        <Metric label="业务预期收益" value={percent(result.business.expected_return, 2)} note={`理论 ${percent(summary.expected_return, 2)}`} />
                        <Metric label="业务组合波动" value={percent(result.business.portfolio_volatility, 2)} note={`理论 ${percent(summary.portfolio_volatility, 2)}`} />
                        <Metric label="业务持仓数" value={`${formatNumber(result.business.holdings_count)} 款`} note={`理论 ${formatNumber(summary.holdings_count)} 款 · 现金 ${percent(result.business.cash_weight)}`} />
                      </div>
                      <div className="business-note"><b>理论最优 → 业务可执行</b><span>起投金额校正后，保真率量化了落地成本；低于起投门槛的产品被剔除或提升，剩余资金以现金持有。</span></div>
                      <div className="table allocation-table">
                        <table>
                          <thead><tr>{["产品", "最低起投", "业务权重", "业务金额", "理论权重"].map((header) => <th key={header}>{header}</th>)}</tr></thead>
                          <tbody>
                            {result.business.allocations.map((item) => {
                              const theory = result.allocations.find((allocation) => allocation.product_id === item.product_id);
                              return (
                                <tr key={item.product_id}>
                                  <td><b>{item.product_id}</b><small>{item.product_name}</small></td>
                                  <td>{money(item.min_invest)}</td>
                                  <td>{percent(item.weight, 2)}</td>
                                  <td>{money(item.amount)}</td>
                                  <td>{theory ? percent(theory.weight, 2) : "—"}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    <div className="inline-empty">业务可执行层暂不可用，理论最优方案不受影响。</div>
                  )}

                  {customer && onOpenMarketing && (
                    <div className="portfolio-handoff">
                      <span><b>投后衔接</b>方案可执行后，营销工作台负责把推荐落地为触达动作。</span>
                      <button className="secondary" onClick={() => onOpenMarketing(customer.customer_id)}>查看该客户营销策略 →</button>
                    </div>
                  )}
                </div>
              )}

              {resultView === "detail" && (
                <div className="result-view detail-view">
                  <div className="detail-caption"><span><b>当前场景配置明细</b><small>按配置权重从高到低排列</small></span><Status>实时求解结果</Status></div>
                  <div className="table allocation-table">
                    <table>
                      <thead><tr>{["产品", "风险", "配置比例", "配置金额", "流动性"].map((header) => <th key={header}>{header}</th>)}</tr></thead>
                      <tbody>
                        {allocations.map((item) => (
                          <tr key={item.product_id}>
                            <td><b>{item.product_id}</b><small>{item.product_name}</small></td>
                            <td><span className="risk-tag">{item.risk_level}</span></td>
                            <td><div className="weight"><i><b style={{ width: `${maxWeight ? item.weight / maxWeight * 100 : 0}%` }} /></i>{percent(item.weight, 2)}</div></td>
                            <td>{money(item.amount)}</td>
                            <td>{item.liquidity}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </>
  );
}
