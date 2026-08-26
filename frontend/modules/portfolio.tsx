"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "../shared/api";
import { money } from "../shared/format";
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
  initialCustomerId,
  notify,
  onOpenMarketing,
}: {
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
  const [marketingSignal, setMarketingSignal] = useState<{
    prob: number | null;
    product_name: string | null;
    strategies: Array<{ rank: number; product_name: string }>;
  } | null>(null);
  const [aiText, setAiText] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

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
    if (!customer || !result?.business) {
      setRebalance(null);
      return;
    }
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

  useEffect(() => {
    if (!customer) {
      setMarketingSignal(null);
      return;
    }
    let cancelled = false;
    Promise.all([
      api<{ customers: Array<{ customer_id: string; product_name: string; response_prob: number }> }>(
        `/marketing/roster?keyword=${encodeURIComponent(customer.customer_id)}&size=20`
      )
        .then((data) => data.customers.filter((row) => row.customer_id === customer.customer_id))
        .catch(() => []),
      api<{ items: Array<{ rank: number; product_name: string }> }>(
        `/customers/${customer.customer_id}/strategies`
      )
        .then((data) => data.items)
        .catch(() => []),
    ]).then(([rows, strategies]) => {
      if (cancelled) return;
      const best = [...rows].sort((left, right) => right.response_prob - left.response_prob)[0];
      setMarketingSignal({
        prob: best ? best.response_prob : null,
        product_name: best ? best.product_name : null,
        strategies: strategies.map((item) => ({ rank: item.rank, product_name: item.product_name })),
      });
    });
    return () => {
      cancelled = true;
    };
  }, [customer]);

  useEffect(() => {
    if (resultView === "ai" && result && !aiText && !aiLoading) {
      void loadAiAnalysis();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resultView, result, aiText]);

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
    try {
      const data = await api<CustomerProfile>(
        `/customers/${encodeURIComponent(normalized)}/profile`,
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
      setAiText(null);
    } catch (error) {
      notify(`组合优化失败：${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function loadAiAnalysis() {
    if (!result || aiLoading) return;
    setAiLoading(true);
    try {
      const data = await api<{ text: string }>("/portfolio/ai-analysis", {
        method: "POST",
        body: JSON.stringify({
          customer: customer ? { risk_appetite: customer.risk_appetite, aum: customer.aum } : null,
          summary: result.summary,
          business: result.business ?? null,
          buys: rebalance?.buys ?? [],
          sells: rebalance?.sells ?? [],
          marketing_prob: marketingSignal?.prob ?? null,
        }),
      });
      setAiText(data.text);
    } catch (error) {
      setAiText(null);
      notify(`AI 解读生成失败：${(error as Error).message}`);
    } finally {
      setAiLoading(false);
    }
  }

  async function saveScenario() {
    if (!customer) return;
    setBusy(true);
    try {
      const created = await api<{ scenario_id: string; scenario_name: string }>(
        "/portfolio/scenarios",
        {
          method: "POST",
          body: JSON.stringify({
            scenario_name: `${customer.customer_id} 专属方案`,
            total_amount: totalAmount,
            risk_aversion: riskAversion,
            max_single_weight: maxSingleWeight,
            max_high_risk_weight: maxHighRiskWeight,
            min_liquid_weight: minLiquidWeight,
            min_holdings: minHoldings,
          }),
        }
      );
      notify(`方案已保存为「${created.scenario_name}」，可在场景列表中复用`);
    } catch (error) {
      notify(`方案保存失败：${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }
  const summary = result?.summary;
  const allocations = result?.allocations ?? [];
  const maxWeight = allocations.reduce((current, item) => Math.max(current, item.weight), 0);
  const guards = summary && result
    ? [
        { name: "总仓位", rule: "产品合计≤100%", actual: `${(summary.invested_weight * 100).toFixed(1)}%`, passed: summary.invested_weight <= 1.000001 },
        { name: "单品上限", rule: `不超过${(result.scenario.max_single_weight * 100).toFixed(0)}%`, actual: `${(maxWeight * 100).toFixed(1)}%`, passed: maxWeight <= result.scenario.max_single_weight + 1e-6 },
        { name: "高风险仓位", rule: `不超过${(result.scenario.max_high_risk_weight * 100).toFixed(0)}%`, actual: `${(summary.high_risk_weight * 100).toFixed(1)}%`, passed: summary.high_risk_weight <= result.scenario.max_high_risk_weight + 1e-6 },
        { name: "流动性", rule: `至少${(result.scenario.min_liquid_weight * 100).toFixed(0)}%`, actual: `${(summary.liquid_plus_cash * 100).toFixed(1)}%`, passed: summary.liquid_plus_cash >= result.scenario.min_liquid_weight - 1e-6 },
        { name: "分散度", rule: `至少${result.scenario.min_holdings}款`, actual: `${summary.holdings_count}款`, passed: summary.holdings_count >= result.scenario.min_holdings },
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
  const explanation = summary && result
    ? (() => {
        const riskTone = result.scenario.risk_aversion >= 2
          ? "优先控制组合波动"
          : result.scenario.risk_aversion >= 1.2
            ? "兼顾收益与风险"
            : "适度提高收益权重";
        const highRiskRoom = Math.max(
          0,
          result.scenario.max_high_risk_weight - summary.high_risk_weight,
        );
        const liquidRoom = Math.max(
          0,
          summary.liquid_plus_cash - result.scenario.min_liquid_weight,
        );
        const lead = allocations[0];
        const clientText = parameterSource === "customer" && customer
          ? `已按${customer.customer_id}的${customer.risk_appetite}${riskNames[customer.risk_appetite]}偏好生成。`
          : "当前方案按所选场景参数生成。";
        const leadText = lead
          ? `最高配置为${lead.product_name}（${(lead.weight * 100).toFixed(1)}%）。`
          : "组合保留全部资金为现金。";
        const gapText = summary.optimality_gap <= 1e-8
          ? "接近0"
          : `为${summary.optimality_gap.toExponential(1)}`;
        return `${clientText}λ=${result.scenario.risk_aversion.toFixed(2)}，${riskTone}；${leadText}高风险仓位仍有${(highRiskRoom * 100).toFixed(1)}个百分点余量，流动性高于下限${(liquidRoom * 100).toFixed(1)}个百分点，最优性gap${gapText}。`;
      })()
    : "";
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
          <div className="portfolio-hero-tags"><i>{officialCount || 20}个场景</i><i>30个产品</i><i>5类硬约束</i></div>
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
                <small>{customer.vip_level} · AUM ¥{money(customer.aum).replace("¥ ", "")}</small>
                <button onClick={applyCustomerRisk}>应用{customer.risk_appetite}参数</button>
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
                <div><h2>组合驾驶舱</h2><p>{activeScenarioLabel} · 配置金额¥{money(totalAmount).replace("¥ ", "")}</p></div>
                <div className="result-tabs">
                  <button className={resultView === "overview" ? "on" : ""} onClick={() => setResultView("overview")}>组合概览</button>
                  <button className={resultView === "business" ? "on" : ""} onClick={() => setResultView("business")}>业务落地</button>
                  <button className={resultView === "detail" ? "on" : ""} onClick={() => setResultView("detail")}>产品明细</button>
                  <button className={resultView === "guards" ? "on" : ""} onClick={() => setResultView("guards")}>合规校验</button>
                  <button className={resultView === "ai" ? "on" : ""} onClick={() => setResultView("ai")}>AI分析</button>
                </div>
                <Status warn={!allPassed}>{allPassed ? "全部约束通过" : "存在约束违例"}</Status>
              </div>

              {resultView === "overview" && (
                <div className="result-view">
                  <div className="metrics">
                    <Metric label="预期年化收益" value={`${(summary.expected_return * 100).toFixed(2)}%`} note="组合加权收益" gold />
                    <Metric label="组合波动率" value={`${(summary.portfolio_volatility * 100).toFixed(2)}%`} note="相关矩阵计算" />
                    <Metric label="组合效用 U" value={summary.utility.toFixed(4)} note="Part B核心目标" />
                    <Metric label="最优性 gap" value={summary.optimality_gap.toExponential(1)} note="接近0表示近优" />
                  </div>

                  <div className="allocation-visual">
                    <div className="allocation-visual-head"><span><b>资产配置分布</b><small>{summary.holdings_count}款产品 + 现金仓位</small></span><strong>{(summary.invested_weight * 100).toFixed(1)}%<small>已投资</small></strong></div>
                    <div className="allocation-stack">
                      {distribution.map((item, index) => <i key={item.label} title={`${item.label} ${(item.weight * 100).toFixed(1)}%`} style={{ width: `${item.weight * 100}%`, background: allocationColors[index % allocationColors.length] }} />)}
                    </div>
                    <div className="allocation-legend">
                      {distribution.map((item, index) => <span key={item.label}><i style={{ background: allocationColors[index % allocationColors.length] }} /><b>{item.label}</b><em>{(item.weight * 100).toFixed(1)}%</em></span>)}
                    </div>
                  </div>

                  {result?.business && (
                    <div className="theory-business-bridge">
                      <div className="bridge-side">
                        <small>理论最优方案</small>
                        <b>{summary.holdings_count} 款产品</b>
                        <span>收益 {(summary.expected_return * 100).toFixed(2)}% · 现金 {(summary.cash_weight * 100).toFixed(1)}%</span>
                      </div>
                      <div className="bridge-core">
                        <em>业务保真率</em>
                        <strong>{result.business.retention_ratio != null ? `${(result.business.retention_ratio * 100).toFixed(1)}%` : "—"}</strong>
                        <button className="secondary" onClick={() => setResultView("business")}>查看业务落地明细 →</button>
                      </div>
                      <div className="bridge-side">
                        <small>业务可执行方案</small>
                        <b>{result.business.holdings_count} 款产品</b>
                        <span>收益 {(result.business.expected_return * 100).toFixed(2)}% · 现金 {(result.business.cash_weight * 100).toFixed(1)}%</span>
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
                <div className="result-view portfolio-ai-page">
                  <section className="portfolio-ai-brief">
                    <div className="portfolio-ai-mark">AI</div>
                    <div>
                      <small>AI ANALYSIS</small>
                      <h3>AI 组合解读</h3>
                      <p>{aiLoading ? "AI 正在分析组合方案…" : (aiText || explanation)}</p>
                    </div>
                    <Status>{aiLoading ? "生成中" : "DeepSeek 实时解读"}</Status>
                  </section>
                  <div className="portfolio-ai-evidence">
                    <article>
                      <small>客户适配证据</small>
                      <b>{customer ? `${customer.risk_appetite} · ${riskNames[customer.risk_appetite]}` : `${scenarioId}场景`}</b>
                      <p>{customer ? `${customer.customer_id}，AUM ¥${money(customer.aum).replace("¥ ", "")}` : "当前未绑定客户画像，按场景参数解释"}</p>
                    </article>
                    <article>
                      <small>风险收益证据</small>
                      <b>λ {result.scenario.risk_aversion.toFixed(2)}</b>
                      <p>预期收益{(summary.expected_return * 100).toFixed(2)}%，组合波动{(summary.portfolio_volatility * 100).toFixed(2)}%</p>
                    </article>
                    <article>
                      <small>优化可信证据</small>
                      <b>gap {summary.optimality_gap.toExponential(1)}</b>
                      <p>{guards.filter((item) => item.passed).length}/{guards.length}项硬约束通过，结果已独立复验</p>
                    </article>
                  </div>
                  <div className="portfolio-ai-trace">
                    <span><b>解释输入</b> 客户画像 · 场景参数 · 组合指标 · 约束校验</span>
                    <p>AI解读用于辅助客户经理理解方案，不替代客户适当性、产品准入和起投金额校验。</p>
                  </div>

                  {rebalance && (
                    <section className="portfolio-ai-advice">
                      <div className="ai-advice-head">
                        <span><small>EXECUTION ADVICE</small><h3>执行建议</h3></span>
                        <p>基于业务可执行方案与当前持仓的差异，AI 给出落地调仓清单。</p>
                      </div>
                      <div className="ai-advice-grid">
                        <div className="ai-advice-col buy">
                          <b>建议买入</b>
                          {rebalance.buys.length ? (
                            <ul>{rebalance.buys.map((item) => <li key={item.product_id}><span>{item.product_name}</span><em>+ ¥{money(item.amount).replace("¥ ", "")}</em></li>)}</ul>
                          ) : <div className="inline-empty">持仓已覆盖方案</div>}
                        </div>
                        <div className="ai-advice-col sell">
                          <b>建议卖出</b>
                          {rebalance.sells.length ? (
                            <ul>{rebalance.sells.map((item) => <li key={item.product_id}><span>{item.product_name}</span><em>- ¥{money(item.amount).replace("¥ ", "")}</em></li>)}</ul>
                          ) : <div className="inline-empty">无需卖出</div>}
                        </div>
                        <div className="ai-advice-summary">
                          <b>净调仓</b>
                          <strong>¥{money(Math.max(0, rebalance.buys.reduce((sum, item) => sum + item.amount, 0) - rebalance.sells.reduce((sum, item) => sum + item.amount, 0))).replace("¥ ", "")}</strong>
                          <button className="secondary" disabled={busy} onClick={() => void saveScenario()}>保存方案</button>
                          <small>保存后可复用 · 不影响官方提交文件</small>
                        </div>
                      </div>
                    </section>
                  )}

                  {marketingSignal && (
                    <section className="portfolio-ai-marketing">
                      <div className="ai-marketing-head">
                        <span><small>MARKETING LINKAGE</small><h3>营销信号联动</h3></span>
                        <Status>AI 综合建议</Status>
                      </div>
                      <p>
                        {marketingSignal.prob != null ? (
                          <>AI 识别该客户为<strong>高意向客户</strong>：A1 响应概率 <strong>{(marketingSignal.prob * 100).toFixed(1)}%</strong>（{marketingSignal.product_name}）。</>
                        ) : (
                          <>该客户不在 A1 触达名单，建议通过画像与持仓线索维护关系。</>
                        )}
                        {marketingSignal.strategies.length ? (
                          <>已生成 Top3 营销策略，投后同步跟进可衔接投顾与营销闭环。</>
                        ) : (
                          <>未覆盖 A2 目标名单，可在营销工作台按需生成策略。</>
                        )}
                      </p>
                      {marketingSignal.strategies.length > 0 && (
                        <div className="ai-marketing-top3">
                          {marketingSignal.strategies.map((item) => (
                            <span key={item.rank}><b>TOP{item.rank}</b>{item.product_name}</span>
                          ))}
                        </div>
                      )}
                      <button className="secondary" onClick={() => onOpenMarketing?.(customer.customer_id)}>
                        查看该客户营销策略 →
                      </button>
                    </section>
                  )}
                </div>
              )}

              {resultView === "business" && (
                <div className="result-view business-view">
                  {result?.business ? (
                    <>
                      <div className="business-metrics">
                        <Metric label="业务保真率" value={result.business.retention_ratio != null ? `${(result.business.retention_ratio * 100).toFixed(1)}%` : "—"} note="业务效用 ÷ 理论效用" gold />
                        <Metric label="业务预期收益" value={`${(result.business.expected_return * 100).toFixed(2)}%`} note={`理论 ${(summary.expected_return * 100).toFixed(2)}%`} />
                        <Metric label="业务组合波动" value={`${(result.business.portfolio_volatility * 100).toFixed(2)}%`} note={`理论 ${(summary.portfolio_volatility * 100).toFixed(2)}%`} />
                        <Metric label="业务持仓数" value={`${result.business.holdings_count} 款`} note={`理论 ${summary.holdings_count} 款 · 现金 ${(result.business.cash_weight * 100).toFixed(1)}%`} />
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
                                  <td>¥{item.min_invest.toLocaleString("zh-CN")}</td>
                                  <td>{(item.weight * 100).toFixed(2)}%</td>
                                  <td>¥{item.amount.toLocaleString("zh-CN")}</td>
                                  <td>{theory ? `${(theory.weight * 100).toFixed(2)}%` : "—"}</td>
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
                            <td><div className="weight"><i><b style={{ width: `${maxWeight ? item.weight / maxWeight * 100 : 0}%` }} /></i>{(item.weight * 100).toFixed(2)}%</div></td>
                            <td>¥{money(item.amount).replace("¥ ", "")}</td>
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
