"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "../shared/api";
import { channelNames, Status } from "../shared/ui";

type TaskStatus = "all" | "pending" | "follow_up" | "converted";
type StrategyDetailTab = "why" | "compliance" | "script";
type ActionTab = "progress" | "attribution" | "lineage";
type Drawer = "opportunities" | "model" | "lab" | null;

const TASK_PAGE_SIZE = 12;
const ROSTER_PAGE_SIZE = 9;

const taskStatusNames: Record<TaskStatus, string> = {
  all: "全部",
  pending: "待联系",
  follow_up: "等待回流",
  converted: "已转化",
};

const ruleNames: Record<string, string> = {
  risk_match: "风险等级适配",
  product_launched: "产品准入检查",
  customer_registered: "客户关系有效",
  duration_valid: "产品期限留痕",
  channel_app_requires_app: "App渠道资格",
  channel_call_complaint_block: "投诉与外呼限制",
  slot_in_enum: "联系时段合规",
  script_length: "话术长度检查",
  script_compliance_note: "风险提示完整",
};

interface MarketingTask {
  customer_id: string;
  risk_appetite: string;
  vip_level: string;
  aum: number;
  status: Exclude<TaskStatus, "all">;
  strategy_id: string | null;
  official_target: boolean;
  strategy_ready: boolean;
  strategy_source: "official_submission" | "live_generated" | "live_on_demand";
  product_id: string | null;
  product_name: string | null;
  risk_level: string | null;
  expected_return: number | null;
  recommended_channel: string | null;
  recommended_time: string | null;
  response_prob: number | null;
  opportunity_score: number | null;
  opportunity_source: "a1_contact" | "not_in_a1_contacts";
  model_contact_id: string | null;
  opportunity_product_id: string | null;
  opportunity_product_name: string | null;
  opportunity_channel: string | null;
  opportunity_date: string | null;
}

interface RosterRow {
  contact_id: string;
  customer_id: string;
  product_id: string;
  product_name: string;
  risk_level: string;
  channel: string;
  contact_date: string;
  response_prob: number;
  strategy_eligible?: boolean;
  rank?: number;
}

interface RosterFilters {
  date: string;
  keyword: string;
  channel: string;
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
  product_type?: string;
  risk_level: string;
  expected_return: number;
  recommended_channel: string;
  recommended_time: string;
  marketing_script: string;
  script_adjusted?: boolean;
  score?: number | null;
  model_prob?: number | null;
  ltr_score?: number | null;
  execution_enabled?: boolean;
  status: "待执行" | "已触达" | "已响应";
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

interface SimulatedHoldingResult {
  holding: {
    holding_id: string;
    customer_id: string;
    product_id: string;
    amount: number;
    buy_date: string;
    attributed_strategy_id: string;
  };
  event: CampaignEvent & { attribution: string; rank: number };
  kpi_delta: { responded: number; manager_conversion: number };
  demo: true;
}

interface PredictionEvidence {
  probability: number;
  decision: string;
  decision_label: string;
  model_name: string;
  as_of: string;
  reasons: string[];
}

interface GeneratedItem {
  rank: number;
  product_id: string;
  product_name: string;
  model_prob: number;
  ltr_score?: number | null;
}

interface GeneratedResult {
  customer_id: string;
  strategy_date: string;
  parameters: {
    manager_quota: number;
    top_n: number;
    ranking_source?: string;
    a1_source?: string;
  };
  items: GeneratedItem[];
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
    channel_distribution: Record<string, number>;
  };
  events: {
    available: boolean;
    sent: number;
    responded: number;
    sent_customers?: number;
    responded_customers?: number;
  };
  kpis: {
    kpi_id: string;
    label: string;
    actual: number;
    target: number;
    unit: string;
  }[];
}

interface MarketingPageProps {
  initialCustomerId: string;
  initialCohort?: "all" | "expiry";
  onOpenCustomer: (customerId: string) => void;
  notify: (message: string) => void;
}

function money(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value);
}

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatTime(value: string) {
  return value.replace("T", " ").slice(5, 16);
}

export function MarketingPage({
  initialCustomerId,
  initialCohort,
  onOpenCustomer,
  notify,
}: MarketingPageProps) {
  const [tasks, setTasks] = useState<MarketingTask[]>([]);
  const [taskCounts, setTaskCounts] = useState<Record<TaskStatus, number>>({
    all: 8000,
    pending: 0,
    follow_up: 0,
    converted: 0,
  });
  const [taskStatus, setTaskStatus] = useState<TaskStatus>("all");
  const [taskCohort, setTaskCohort] = useState<"all" | "expiry">("all");
  const [taskPage, setTaskPage] = useState(1);
  const [taskTotal, setTaskTotal] = useState(0);
  const [taskQuery, setTaskQuery] = useState("");
  const [taskLoading, setTaskLoading] = useState(false);
  const [taskPopulation, setTaskPopulation] = useState(8000);
  const [officialTargetCount, setOfficialTargetCount] = useState(2000);
  const [modelCoveredCustomers, setModelCoveredCustomers] = useState(5031);
  const taskSearchTimer = useRef<number | null>(null);
  const taskRequestId = useRef(0);
  const rosterRequestId = useRef(0);
  const strategyRequestId = useRef(0);
  const evidenceRequestId = useRef(0);
  const generationRequestId = useRef(0);

  const [summary, setSummary] = useState<MarketingSummary | null>(null);
  const [strategyInput, setStrategyInput] = useState(initialCustomerId || "C000010");
  const [strategyCustomerId, setStrategyCustomerId] = useState(initialCustomerId || "");
  const [strategyDate, setStrategyDate] = useState("2026-04-15");
  const [riskAppetite, setRiskAppetite] = useState("—");
  const [customerVipLevel, setCustomerVipLevel] = useState("—");
  const [strategyOfficialTarget, setStrategyOfficialTarget] = useState(false);
  const [strategySource, setStrategySource] = useState<"official_submission" | "live_generated">("official_submission");
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [selectedOpportunity, setSelectedOpportunity] = useState<MarketingTask | null>(null);
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [selectedRank, setSelectedRank] = useState(1);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [detailTab, setDetailTab] = useState<StrategyDetailTab>("why");
  const [actionTab, setActionTab] = useState<ActionTab>("progress");
  const [predictionEvidence, setPredictionEvidence] = useState<PredictionEvidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const [drawer, setDrawer] = useState<Drawer>(null);
  const [showSimulation, setShowSimulation] = useState(false);
  const [simulationDate, setSimulationDate] = useState("2026-04-20");
  const [simulationAmount, setSimulationAmount] = useState(50000);
  const [lastSimulation, setLastSimulation] = useState<SimulatedHoldingResult | null>(null);

  const [roster, setRoster] = useState<RosterRow[]>([]);
  const [rosterTotal, setRosterTotal] = useState(0);
  const [rosterPage, setRosterPage] = useState(1);
  const [rosterDate, setRosterDate] = useState("2026-04-15");
  const [rosterDates, setRosterDates] = useState<{ date: string; scope: string }[]>([]);
  const [rosterQuery, setRosterQuery] = useState("");
  const [rosterChannel, setRosterChannel] = useState("");
  const [rosterLoading, setRosterLoading] = useState(false);
  const [appliedRosterFilters, setAppliedRosterFilters] = useState<RosterFilters>({
    date: "2026-04-15",
    keyword: "",
    channel: "",
  });

  const [quota, setQuota] = useState(600);
  const [generated, setGenerated] = useState<GeneratedResult | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    void loadTasks(1, "all", "");
    void loadSummary();
  }, []);

  useEffect(() => {
    if (initialCohort && initialCohort !== taskCohort) {
      setTaskCohort(initialCohort);
      void loadTasks(1, taskStatus, taskQuery, initialCohort);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCohort]);

  useEffect(() => {
    if (initialCustomerId) void loadStrategies(initialCustomerId);
  }, [initialCustomerId]);

  useEffect(() => {
    if (!drawer && !showSimulation) return undefined;
    const closeLayer = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawer(null);
        setShowSimulation(false);
      }
    };
    window.addEventListener("keydown", closeLayer);
    return () => window.removeEventListener("keydown", closeLayer);
  }, [drawer, showSimulation]);

  useEffect(() => () => {
    if (taskSearchTimer.current) window.clearTimeout(taskSearchTimer.current);
  }, []);

  async function loadSummary() {
    try {
      setSummary(await api<MarketingSummary>("/dashboard/summary"));
    } catch (error) {
      notify(`经营指标加载失败：${(error as Error).message}`);
    }
  }

  async function loadTasks(
    page: number,
    status: TaskStatus = taskStatus,
    keyword: string = taskQuery,
    cohort: "all" | "expiry" = taskCohort,
  ) {
    const requestId = ++taskRequestId.current;
    setTaskLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        size: String(TASK_PAGE_SIZE),
        status,
        cohort,
      });
      if (keyword.trim()) params.set("keyword", keyword.trim());
      const data = await api<{
        total: number;
        population_total: number;
        official_target_customers: number;
        model_covered_customers: number;
        counts: Record<TaskStatus, number>;
        tasks: MarketingTask[];
      }>(`/marketing/tasks?${params.toString()}`);
      if (requestId !== taskRequestId.current) return;
      if (page > 1 && data.total > 0 && data.tasks.length === 0) {
        void loadTasks(
          Math.ceil(data.total / TASK_PAGE_SIZE),
          status,
          keyword,
          cohort,
        );
        return;
      }
      setTasks(data.tasks);
      setTaskTotal(data.total);
      setTaskCounts(data.counts);
      setTaskPopulation(data.population_total);
      setOfficialTargetCount(data.official_target_customers);
      setModelCoveredCustomers(data.model_covered_customers);
      setTaskPage(page);
      setTaskStatus(status);
      setTaskCohort(cohort);
    } catch (error) {
      if (requestId === taskRequestId.current) {
        notify(`营销任务加载失败：${(error as Error).message}`);
      }
    } finally {
      if (requestId === taskRequestId.current) setTaskLoading(false);
    }
  }

  function changeTaskStatus(status: TaskStatus) {
    if (taskSearchTimer.current) window.clearTimeout(taskSearchTimer.current);
    setTaskStatus(status);
    void loadTasks(1, status, taskQuery, taskCohort);
  }

  function changeTaskCohort(cohort: "all" | "expiry") {
    setTaskCohort(cohort);
    void loadTasks(1, taskStatus, taskQuery, cohort);
  }

  function changeTaskQuery(value: string) {
    setTaskQuery(value);
    if (taskSearchTimer.current) window.clearTimeout(taskSearchTimer.current);
    taskSearchTimer.current = window.setTimeout(() => {
      void loadTasks(1, taskStatus, value);
    }, 300);
  }

  async function refreshEvents(customerId: string, requestId: number) {
    try {
      const data = await api<{ events: CampaignEvent[] }>(
        `/campaign/events?customer_id=${encodeURIComponent(customerId)}`,
      );
      if (requestId === strategyRequestId.current) setEvents(data.events);
    } catch {
      if (requestId === strategyRequestId.current) setEvents([]);
    }
  }

  async function loadPrediction(customerId: string, item: StrategyItem, dateValue: string) {
    const requestId = ++evidenceRequestId.current;
    setEvidenceLoading(true);
    setPredictionEvidence(null);
    try {
      const data = await api<PredictionEvidence>("/marketing/response/predict", {
          method: "POST",
          body: JSON.stringify({
            customer_id: customerId,
            product_id: item.product_id,
            channel: item.recommended_channel,
            contact_date: dateValue,
          }),
        });
      if (requestId === evidenceRequestId.current) setPredictionEvidence(data);
    } catch {
      if (requestId === evidenceRequestId.current) setPredictionEvidence(null);
    } finally {
      if (requestId === evidenceRequestId.current) setEvidenceLoading(false);
    }
  }

  async function loadStrategies(
    customerId: string,
    preferredRank?: number,
    opportunity?: MarketingTask,
  ) {
    const normalized = customerId.trim().toUpperCase();
    if (!normalized) return;
    const requestId = ++strategyRequestId.current;
    evidenceRequestId.current += 1;
    generationRequestId.current += 1;
    const currentOpportunity = opportunity
      ?? tasks.find((task) => task.customer_id === normalized)
      ?? (selectedOpportunity?.customer_id === normalized ? selectedOpportunity : null);
    setGenerated(null);
    setGenerating(false);
    setStrategyLoading(true);
    setStrategyCustomerId(normalized);
    setStrategyInput(normalized);
    setStrategies([]);
    setEvents([]);
    setPredictionEvidence(null);
    setEvidenceLoading(false);
    setSelectedOpportunity(currentOpportunity);
    setRiskAppetite(currentOpportunity?.risk_appetite ?? "—");
    setCustomerVipLevel(currentOpportunity?.vip_level ?? "客户");
    setStrategyOfficialTarget(currentOpportunity?.official_target ?? false);
    setStrategySource(currentOpportunity?.official_target ? "official_submission" : "live_generated");
    setBusy(true);
    try {
      const data = await api<{
        customer_id: string;
        strategy_date: string;
        official_target: boolean;
        strategy_source: "official_submission" | "live_generated";
        risk_appetite: string;
        vip_level: string;
        aum: number;
        items: StrategyItem[];
      }>(`/customers/${encodeURIComponent(normalized)}/strategies`);
      if (requestId !== strategyRequestId.current) return;
      const next =
        data.items.find((item) => item.rank === preferredRank)
        ?? data.items.find((item) => item.status === "已响应")
        ?? data.items.find((item) => item.status === "已触达")
        ?? data.items.find((item) => item.status === "待执行")
        ?? data.items[0];
      setStrategyCustomerId(normalized);
      setStrategyInput(normalized);
      setStrategyDate(data.strategy_date);
      setRiskAppetite(data.risk_appetite);
      setCustomerVipLevel(data.vip_level);
      setStrategyOfficialTarget(data.official_target);
      setStrategySource(data.strategy_source);
      setStrategies(data.items);
      setSelectedRank(next?.rank ?? 1);
      setDetailTab("why");
      setActionTab("progress");
      setLastSimulation(null);
      setTasks((current) => current.map((task) => (
        task.customer_id === normalized
          ? {
              ...task,
              strategy_id: next?.strategy_id ?? task.strategy_id,
              strategy_ready: true,
              strategy_source: data.strategy_source,
              product_id: next?.product_id ?? task.product_id,
              product_name: next?.product_name ?? task.product_name,
              risk_level: next?.risk_level ?? task.risk_level,
              expected_return: next?.expected_return ?? task.expected_return,
              recommended_channel: next?.recommended_channel ?? task.recommended_channel,
              recommended_time: next?.recommended_time ?? task.recommended_time,
            }
          : task
      )));
      if (currentOpportunity) {
        setSelectedOpportunity({
          ...currentOpportunity,
          strategy_id: next?.strategy_id ?? currentOpportunity.strategy_id,
          strategy_ready: true,
          strategy_source: data.strategy_source,
          product_id: next?.product_id ?? currentOpportunity.product_id,
          product_name: next?.product_name ?? currentOpportunity.product_name,
          risk_level: next?.risk_level ?? currentOpportunity.risk_level,
          expected_return: next?.expected_return ?? currentOpportunity.expected_return,
          recommended_channel: next?.recommended_channel ?? currentOpportunity.recommended_channel,
          recommended_time: next?.recommended_time ?? currentOpportunity.recommended_time,
        });
      }
      if (next) void loadPrediction(normalized, next, data.strategy_date);
      await refreshEvents(normalized, requestId);
    } catch (error) {
      if (requestId === strategyRequestId.current) {
        notify(`客户策略加载失败：${(error as Error).message}`);
      }
    } finally {
      if (requestId === strategyRequestId.current) {
        setBusy(false);
        setStrategyLoading(false);
      }
    }
  }

  function selectStrategy(item: StrategyItem) {
    setSelectedRank(item.rank);
    setDetailTab("why");
    setActionTab("progress");
    setLastSimulation(null);
    void loadPrediction(strategyCustomerId, item, strategyDate);
  }

  async function completeContact() {
    if (!selectedStrategy) return;
    setBusy(true);
    try {
      await api<CampaignEvent>("/campaign/events", {
        method: "POST",
        body: JSON.stringify({
          event_type: "sent",
          strategy_id: selectedStrategy.strategy_id,
        }),
      });
      notify("本次联系已完成，系统开始等待客户购买回流");
      await loadStrategies(strategyCustomerId, selectedStrategy.rank);
      await Promise.all([
        loadSummary(),
        loadTasks(taskPage, taskStatus, taskQuery),
      ]);
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function simulateHolding() {
    if (!selectedStrategy) return;
    setBusy(true);
    try {
      const result = await api<SimulatedHoldingResult>("/campaign/demo-holdings", {
        method: "POST",
        body: JSON.stringify({
          customer_id: strategyCustomerId,
          product_id: selectedStrategy.product_id,
          buy_date: simulationDate,
          amount: simulationAmount,
        }),
      });
      setShowSimulation(false);
      await loadStrategies(strategyCustomerId, selectedStrategy.rank);
      await Promise.all([
        loadSummary(),
        loadTasks(taskPage, taskStatus, taskQuery),
      ]);
      setLastSimulation(result);
      setActionTab("attribution");
      notify(
        result.kpi_delta.manager_conversion > 0
          ? "已检测到新增持仓，自动归因成功，客户经理转化 KPI +1"
          : "已检测到新增持仓并自动归因，活动响应 +1；该渠道不增加经理专属 KPI",
      );
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copyScript() {
    if (!selectedStrategy) return;
    try {
      await navigator.clipboard.writeText(selectedStrategy.marketing_script);
      notify("标准营销话术已复制");
    } catch {
      notify("复制失败，请手动选择话术文本");
    }
  }

  async function loadRoster(
    page: number,
    filters: RosterFilters = appliedRosterFilters,
  ) {
    const requestId = ++rosterRequestId.current;
    setRosterLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        size: String(ROSTER_PAGE_SIZE),
        sort: "prob_desc",
        contact_date: filters.date,
      });
      if (filters.keyword.trim()) params.set("keyword", filters.keyword.trim());
      if (filters.channel) params.set("channel", filters.channel);
      const data = await api<{
        total: number;
        customers: RosterRow[];
        dates: { date: string; scope: string }[];
      }>(`/marketing/roster?${params.toString()}`);
      if (requestId !== rosterRequestId.current) return;
      setRoster(data.customers);
      setRosterTotal(data.total);
      setRosterPage(page);
      if (data.dates.length) setRosterDates(data.dates);
    } catch (error) {
      if (requestId === rosterRequestId.current) {
        notify(`模型机会池加载失败：${(error as Error).message}`);
      }
    } finally {
      if (requestId === rosterRequestId.current) setRosterLoading(false);
    }
  }

  function openOpportunityPool() {
    const filters = {
      date: rosterDate,
      keyword: rosterQuery,
      channel: rosterChannel,
    };
    setAppliedRosterFilters(filters);
    setDrawer("opportunities");
    void loadRoster(1, filters);
  }

  function applyRosterFilters() {
    const filters = {
      date: rosterDate,
      keyword: rosterQuery,
      channel: rosterChannel,
    };
    setAppliedRosterFilters(filters);
    void loadRoster(1, filters);
  }

  async function regenerate() {
    if (!strategyCustomerId) return;
    const requestId = ++generationRequestId.current;
    setGenerating(true);
    setGenerated(null);
    try {
      const data = await api<GeneratedResult>("/marketing/strategy/generate", {
        method: "POST",
        body: JSON.stringify({
          customer_id: strategyCustomerId,
          manager_quota: quota,
        }),
      });
      if (requestId === generationRequestId.current) {
        setGenerated(data);
        notify("策略试算完成，正式提交结果未被覆盖");
      }
    } catch (error) {
      if (requestId === generationRequestId.current) {
        notify(`策略试算失败：${(error as Error).message}`);
      }
    } finally {
      if (requestId === generationRequestId.current) setGenerating(false);
    }
  }

  const selectedStrategy =
    strategies.find((item) => item.rank === selectedRank) ?? strategies[0];
  const selectedTask = tasks.find((task) => task.customer_id === strategyCustomerId)
    ?? (selectedOpportunity?.customer_id === strategyCustomerId ? selectedOpportunity : undefined);
  const selectedPassedRules = selectedStrategy?.rule_trace.filter((rule) => rule.passed) ?? [];
  const selectedFailedRules = selectedStrategy?.rule_trace.filter((rule) => !rule.passed) ?? [];
  const selectedResponseEvent = [...events]
    .reverse()
    .find(
      (event) =>
        event.strategy_id === selectedStrategy?.strategy_id
        && event.event_type === "responded",
    );
  const managerKpi = summary?.kpis.find((item) => item.kpi_id === "manager_conversion");
  const eventServiceAvailable = summary?.events.available === true;
  const taskPageCount = Math.max(1, Math.ceil(taskTotal / TASK_PAGE_SIZE));
  const rosterPageCount = Math.max(1, Math.ceil(rosterTotal / ROSTER_PAGE_SIZE));

  const riskReason = selectedStrategy?.rule_trace.find(
    (rule) => rule.rule_id === "risk_match",
  )?.reason;
  const evidenceReasons = selectedStrategy
    ? [
        predictionEvidence
          ? `A1 对当前客户 × ${selectedStrategy.product_id} × ${channelNames[selectedStrategy.recommended_channel]} 的在线复核概率为 ${percent(predictionEvidence.probability)}，${predictionEvidence.decision_label}。`
          : "产品级在线复核暂未完成；任务池中的客户最高机会分不替代当前产品概率。",
        riskReason ?? `客户风险偏好 ${riskAppetite}，产品风险 ${selectedStrategy.risk_level}。`,
        `建议通过${channelNames[selectedStrategy.recommended_channel]}在${selectedStrategy.recommended_time}联系，渠道、时段和执行规则已逐项留痕。`,
      ]
    : [];

  return (
    <section className="manager-marketing-shell">
      <header className="manager-marketing-head">
        <div className="manager-title">
          <small>4月财富营销活动 · 客户经理 MGR001</small>
          <h1>营销运营工作台</h1>
          <p>从客户机会、个性化策略到联系跟进和转化归因，全部在同一任务中完成。</p>
        </div>
        <div className="manager-kpis">
          <div><small>全量客户</small><strong>{taskPopulation.toLocaleString()}</strong><span>A2正式目标 {officialTargetCount.toLocaleString()} 人</span></div>
          <div><small>A1机会覆盖</small><strong>{modelCoveredCustomers.toLocaleString()}</strong><span>有离线触达评分的客户</span></div>
          <div><small>已转化客户</small><strong>{eventServiceAvailable ? summary?.events.responded_customers ?? summary?.events.responded : "—"}</strong><span>{eventServiceAvailable ? "自动归因客户数" : "事件服务暂不可用"}</span></div>
          <div className="target"><small>我的本月目标</small><strong>{eventServiceAvailable ? managerKpi?.actual ?? "—" : "—"}<i>/ {managerKpi?.target ?? 30}</i></strong><span>客户经理转化数</span></div>
        </div>
        <div className="manager-head-actions">
          <button onClick={openOpportunityPool}>A1 模型机会池</button>
          <button onClick={() => setDrawer("model")}>模型与数据证据</button>
        </div>
      </header>

      <div className="manager-workspace">
        <aside className="task-pane">
          <header>
            <div><small>客户机会</small><h2>全量客户队列</h2></div>
            <Status>{taskLoading ? "更新中" : `${taskTotal}人`}</Status>
          </header>
          <nav className="task-status-tabs">
            {(Object.keys(taskStatusNames) as TaskStatus[]).map((status) => (
              <button
                className={taskStatus === status ? "on" : ""}
                key={status}
                onClick={() => changeTaskStatus(status)}
              >
                <span>{taskStatusNames[status]}</span>
                <b>{taskCounts[status]}</b>
              </button>
            ))}
          </nav>
          <div className="task-cohort">
            <button
              className={taskCohort === "all" ? "on" : ""}
              onClick={() => changeTaskCohort("all")}
            >
              全部客户
            </button>
            <button
              className={taskCohort === "expiry" ? "on" : ""}
              onClick={() => changeTaskCohort("expiry")}
            >
              到期跟进
            </button>
          </div>
          <div className="task-search">
            <input
              aria-label="搜索营销任务"
              placeholder="搜索客户或机会产品"
              value={taskQuery}
              onChange={(event) => changeTaskQuery(event.target.value)}
            />
          </div>
          <div className="task-list">
            {tasks.map((task) => {
              const opportunityChannel = task.opportunity_channel
                ? channelNames[task.opportunity_channel]
                : "暂无A1触达";
              return (
                <button
                  className={strategyCustomerId === task.customer_id ? "task-card selected" : "task-card"}
                  disabled={busy}
                  key={task.customer_id}
                  onClick={() => void loadStrategies(task.customer_id, undefined, task)}
                >
                  <span className="task-card-head">
                    <b>{task.customer_id}</b>
                    <span className="task-card-badges">
                      {task.official_target && <em className="a2">A2目标</em>}
                      {!task.official_target && task.strategy_ready && <em className="ready">Top3就绪</em>}
                      <em className={task.status}>{taskStatusNames[task.status]}</em>
                    </span>
                  </span>
                  <strong>{task.opportunity_product_name ? `机会产品 · ${task.opportunity_product_name}` : "暂无离线机会分"}</strong>
                  <small>{task.vip_level} · {task.risk_appetite} · {opportunityChannel}</small>
                  <span className="task-signal">
                    <i><b style={{ width: `${(task.opportunity_score ?? 0) * 100}%` }} /></i>
                    <em>{task.opportunity_score == null ? "未进入A1测试触达 · 可实时生成" : `${percent(task.opportunity_score)} 客户最高机会`}</em>
                  </span>
                </button>
              );
            })}
            {!taskLoading && tasks.length === 0 && (
              <div className="task-empty">当前条件下没有营销任务</div>
            )}
          </div>
          <footer className="pane-pagination">
            <button disabled={taskPage <= 1} onClick={() => void loadTasks(taskPage - 1)}>‹</button>
            <span>{taskPage} / {taskPageCount}</span>
            <button disabled={taskPage >= taskPageCount} onClick={() => void loadTasks(taskPage + 1)}>›</button>
          </footer>
        </aside>

        <section className="strategy-pane">
          <header className="customer-context">
            <div className="avatar">{strategyCustomerId.slice(-2) || "—"}</div>
            <span>
              <small className="strategy-source-line">
                {strategyCustomerId && (
                  <i className={strategyOfficialTarget ? "official" : "live"}>
                    {strategyOfficialTarget ? "A2目标 · 正式Top3" : "全量客户 · 实时Top3"}
                  </i>
                )}
                当前客户
              </small>
              <strong>{strategyCustomerId || "请选择左侧客户任务"}</strong>
              <em>{strategyCustomerId ? `${selectedTask?.vip_level ?? customerVipLevel} · 风险偏好 ${riskAppetite} · ${strategyOfficialTarget ? "策略日" : "计算日"} ${strategyDate}` : "按客户最高机会分排序，点击后查看Top3"}</em>
            </span>
            <div className="customer-context-actions">
              <input
                aria-label="跳转客户编号"
                value={strategyInput}
                onChange={(event) => setStrategyInput(event.target.value)}
              />
              <button disabled={busy} onClick={() => void loadStrategies(strategyInput)}>跳转</button>
              <button disabled={!strategyCustomerId || busy} onClick={() => onOpenCustomer(strategyCustomerId)}>查看画像</button>
              <button disabled={!strategyCustomerId || busy} className="lab" onClick={() => setDrawer("lab")}>策略试算</button>
            </div>
          </header>

          {strategyLoading ? (
            <div className="strategy-loading-new">
              <i />
              <b>{strategyOfficialTarget ? "正在加载正式 Top3" : "正在计算并冻结实时 Top3"}</b>
              <p>{strategyOfficialTarget ? "读取赛事正式提交结果与执行规则。" : "首次打开会基于当前客户特征生成，后续直接复用同一快照。"}</p>
            </div>
          ) : selectedStrategy ? (
            <>
              <div className="top3-strip">
                {strategies.map((item) => (
                  <button
                    className={item.rank === selectedStrategy.rank ? "selected" : ""}
                    key={item.strategy_id}
                    onClick={() => selectStrategy(item)}
                  >
                    <b>TOP {item.rank}</b>
                    <span><strong>{item.product_name}</strong><small>{item.product_id} · {item.risk_level}</small></span>
                    <em className={item.status}>{item.status}</em>
                  </button>
                ))}
              </div>

              <article className="strategy-detail">
                <header className="strategy-detail-head">
                  <div>
                    <small>{strategySource === "official_submission" ? "正式提交策略" : "实时策略快照"} · TOP {selectedStrategy.rank}</small>
                    <h2>{selectedStrategy.product_name}</h2>
                    <p>{selectedStrategy.product_type ?? "财富产品"} · 风险 {selectedStrategy.risk_level} · 预期年化 {percent(selectedStrategy.expected_return)}</p>
                  </div>
                  <div className="strategy-route">
                    <span><small>建议渠道</small><b>{channelNames[selectedStrategy.recommended_channel]}</b></span>
                    <span><small>最佳时段</small><b>{selectedStrategy.recommended_time}</b></span>
                  </div>
                </header>

                <nav className="strategy-detail-tabs">
                  <button className={detailTab === "why" ? "on" : ""} onClick={() => setDetailTab("why")}>为什么推荐</button>
                  <button className={detailTab === "compliance" ? "on" : ""} onClick={() => setDetailTab("compliance")}>合规检查 <i>{selectedPassedRules.length}/{selectedStrategy.rule_trace.length}</i></button>
                  <button className={detailTab === "script" ? "on" : ""} onClick={() => setDetailTab("script")}>执行话术</button>
                </nav>

                <div className="strategy-detail-body">
                  {detailTab === "why" && (
                    <div className="why-view">
                      <div className="signal-cards">
                        <article><small>A1产品级在线复核</small><strong>{evidenceLoading ? "计算中" : predictionEvidence ? percent(predictionEvidence.probability) : "待复核"}</strong><span>{predictionEvidence?.decision_label ?? (selectedTask?.response_prob != null ? `任务池客户最高机会 ${percent(selectedTask.response_prob)}` : "该客户不在A1测试触达中")}</span></article>
                        <article><small>客户风险偏好</small><strong>{riskAppetite}</strong><span>产品风险 {selectedStrategy.risk_level}</span></article>
                        <article><small>产品吸引力</small><strong>{percent(selectedStrategy.expected_return)}</strong><span>预期年化收益</span></article>
                        <article><small>执行适配</small><strong>{channelNames[selectedStrategy.recommended_channel]}</strong><span>{selectedStrategy.recommended_time}</span></article>
                      </div>
                      <section className="recommendation-reasons">
                        <header><small>个性化解释</small><h3>为什么适合向该客户推荐</h3></header>
                        <ul>
                          {evidenceReasons.map((reason, index) => (
                            <li key={`${reason}-${index}`}><b>{index + 1}</b><span>{reason}</span></li>
                          ))}
                        </ul>
                      </section>
                      {predictionEvidence?.reasons?.length ? (
                        <details className="model-reason-details">
                          <summary>查看模型层重要因子</summary>
                          <p>以下为模型全局重要性证据，用于解释模型整体，不等同于单客户的因果归因。</p>
                          <ul>{predictionEvidence.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
                        </details>
                      ) : null}
                      <div className="asof-note"><b>严格 as-of</b><span>客户持仓、行为和历史触达均截断在 {strategyDate} 之前；在线复核与离线训练共用特征口径。</span></div>
                    </div>
                  )}

                  {detailTab === "compliance" && (
                    <div className="compliance-view-new">
                      <header>
                        <b>{selectedPassedRules.length}/{selectedStrategy.rule_trace.length}</b>
                        <span><strong>{selectedFailedRules.length ? "存在需要复核的执行项" : "平台执行检查全部通过"}</strong><small>风险、产品、渠道、时段和话术均留有规则证据</small></span>
                        <Status warn={selectedFailedRules.length > 0}>{selectedFailedRules.length ? "人工复核" : "允许执行"}</Status>
                      </header>
                      <ul>
                        {selectedStrategy.rule_trace.map((rule) => (
                          <li className={rule.passed ? "passed" : "failed"} key={rule.rule_id}>
                            <b>{rule.passed ? "✓" : "!"}</b>
                            <span><strong>{ruleNames[rule.rule_id] ?? rule.rule_id}</strong><small>{rule.reason}</small></span>
                            <em>{rule.passed ? "通过" : "复核"}</em>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {detailTab === "script" && (
                    <div className="script-view-new">
                      <div>
                        <small>标准营销话术 · {selectedStrategy.marketing_script.length}字</small>
                        <p>{selectedStrategy.marketing_script}</p>
                        {selectedStrategy.script_adjusted && <span className="script-safe">平台执行层已自动补全标准风险提示</span>}
                      </div>
                      <aside>
                        <span><small>联系渠道</small><strong>{channelNames[selectedStrategy.recommended_channel]}</strong></span>
                        <span><small>建议时间</small><strong>{selectedStrategy.recommended_time}</strong></span>
                        <button onClick={() => void copyScript()}>复制标准话术</button>
                      </aside>
                    </div>
                  )}
                </div>
              </article>
            </>
          ) : (
            <div className="strategy-empty-new"><b>先从左侧选择一位高机会客户</b><p>系统会读取正式结果或实时生成 Top3，再由客户经理选择一条策略执行联系。</p></div>
          )}
        </section>

        <aside className="action-pane">
          <header>
            <div><small>下一步行动</small><h2>{selectedStrategy?.status ?? "等待选择任务"}</h2></div>
            {selectedStrategy && <Status warn={selectedStrategy.status === "待执行"}>{selectedStrategy.status}</Status>}
          </header>

          {selectedStrategy && (
            <>
              <div className="action-strategy-summary">
                <b>TOP {selectedStrategy.rank}</b>
                <span><strong>{selectedStrategy.product_name}</strong><small>{channelNames[selectedStrategy.recommended_channel]} · {selectedStrategy.recommended_time}</small></span>
              </div>

              <nav className="action-tabs">
                <button className={actionTab === "progress" ? "on" : ""} onClick={() => setActionTab("progress")}>任务进度</button>
                <button className={actionTab === "attribution" ? "on" : ""} onClick={() => setActionTab("attribution")}>归因依据</button>
                <button className={actionTab === "lineage" ? "on" : ""} onClick={() => setActionTab("lineage")}>数据链路</button>
              </nav>

              <div className="action-body">
                {actionTab === "progress" && (
                  <div className="progress-view">
                    <div className="manager-journey">
                      {[
                        ["策略已就绪", true, "Top3、渠道、时段和话术已生成"],
                        ["已完成联系", selectedStrategy.status !== "待执行", "客户经理完成本次触达"],
                        ["购买数据回流", selectedStrategy.status === "已响应", "核心业务系统识别新增持仓"],
                        ["计入营销转化", selectedStrategy.status === "已响应", "窗口和Top3规则自动归因"],
                      ].map(([label, active, hint], index) => (
                        <div className={active ? "active" : ""} key={String(label)}>
                          <i>{active ? "✓" : index + 1}</i>
                          <span><b>{label}</b><small>{hint}</small></span>
                        </div>
                      ))}
                    </div>

                    {selectedStrategy.status === "待执行" && (
                      <div className="next-action-card">
                        <small>建议下一步</small>
                        <h3>按推荐渠道完成本次客户联系</h3>
                        <p>完成后系统将记录联系事实，并等待客户购买数据自动回流。</p>
                        <button
                          disabled={busy || selectedStrategy.execution_enabled === false || selectedFailedRules.length > 0}
                          onClick={() => void completeContact()}
                        >
                          {busy ? "处理中…" : strategyOfficialTarget ? "完成本次联系" : `采用 TOP ${selectedStrategy.rank} 并完成联系`}
                        </button>
                        {selectedFailedRules.length > 0 && <em>请先在“合规检查”中完成人工复核</em>}
                      </div>
                    )}

                    {selectedStrategy.status === "已触达" && (
                      <div className="waiting-card">
                        <b>等待系统识别客户购买</b>
                        <p>客户经理无需手工登记购买；生产环境由 T+1 新增持仓任务自动扫描。</p>
                        <details>
                          <summary>答辩演示工具</summary>
                          <span>仅用于模拟核心业务系统回传一笔新增持仓。</span>
                          <button onClick={() => setShowSimulation(true)}>模拟系统收到新增持仓</button>
                        </details>
                      </div>
                    )}

                    {selectedStrategy.status === "已响应" && (
                      <div className="converted-card">
                        <b>该客户已成功转化</b>
                        <p>{selectedStrategy.recommended_channel === "manager" ? "购买事实已命中推荐策略，并计入客户经理本月转化 KPI。" : "购买事实已命中推荐策略并计入活动响应；该渠道不增加经理专属 KPI。"}</p>
                        <button onClick={() => setActionTab("attribution")}>查看为什么计入本次营销</button>
                      </div>
                    )}
                  </div>
                )}

                {actionTab === "attribution" && (
                  <div className="attribution-view">
                    {selectedResponseEvent ? (
                      <>
                        <div className="attribution-result"><i>✓</i><span><small>归因结论</small><strong>计入本次营销转化</strong><em>命中客户 Top{selectedStrategy.rank} 推荐</em></span></div>
                        <dl>
                          <div><dt>购买产品</dt><dd>{selectedResponseEvent.product_id} · {selectedStrategy.product_name}</dd></div>
                          <div><dt>购买金额</dt><dd>{selectedResponseEvent.amount == null ? "—" : money(selectedResponseEvent.amount)}</dd></div>
                          <div><dt>归因窗口</dt><dd>{strategyDate} 起 30 天内</dd></div>
                          <div><dt>匹配规则</dt><dd>同客户 + Top3产品 + 窗口内 + 首次购买</dd></div>
                          <div><dt>事件时间</dt><dd>{formatTime(selectedResponseEvent.occurred_at)}</dd></div>
                        </dl>
                        {lastSimulation && <div className="demo-proof"><b>演示数据 · 活动响应 +1{lastSimulation.kpi_delta.manager_conversion > 0 ? " · 经理KPI +1" : ""}</b><span>{lastSimulation.holding.holding_id} · {lastSimulation.holding.buy_date}</span></div>}
                      </>
                    ) : (
                      <div className="no-attribution"><b>尚无可归因购买</b><p>完成联系后，系统将监测归因窗口内的新增持仓。</p></div>
                    )}
                  </div>
                )}

                {actionTab === "lineage" && (
                  <div className="lineage-view">
                    <p>业务人员看到的是任务状态，系统在后台保留完整可审计链路。</p>
                    {[
                      ["个性化策略", strategySource === "official_submission" ? "partA_strategy · 正式Top3" : "app_marketing_strategy · 实时Top3快照"],
                      ["客户联系事实", "app_campaign_event · sent"],
                      ["新增持仓回流", "t_holding（生产）/ app_demo_holding（演示）"],
                      ["自动响应归因", "app_campaign_event · responded"],
                      ["经营指标更新", "dashboard · KPI重新聚合"],
                    ].map((item, index) => (
                      <div className="lineage-node" key={item[0]}><i>{index + 1}</i><span><b>{item[0]}</b><small>{item[1]}</small></span>{index < 4 && <em>↓</em>}</div>
                    ))}
                  </div>
                )}
              </div>

              <div className={lastSimulation?.kpi_delta.manager_conversion ? "personal-kpi changed" : "personal-kpi"}>
                <span><small>我的本月转化</small><strong>{eventServiceAvailable ? managerKpi?.actual ?? "—" : "—"} / {managerKpi?.target ?? 30}</strong></span>
                <i><b style={{ width: `${eventServiceAvailable ? Math.min(100, ((managerKpi?.actual ?? 0) / (managerKpi?.target ?? 30)) * 100) : 0}%` }} /></i>
                <em>{lastSimulation?.kpi_delta.manager_conversion ? "本次归因 +1" : eventServiceAvailable ? `完成率 ${Math.round((managerKpi?.actual ?? 0) / (managerKpi?.target ?? 30) * 100)}%` : "事件服务暂不可用"}</em>
              </div>
            </>
          )}
        </aside>
      </div>

      {drawer && (
        <div className="marketing-drawer-layer" role="dialog" aria-modal="true">
          <section className={`marketing-drawer ${drawer}`}>
            <header>
              <div>
                <small>评委验收与高级能力</small>
                <h2>{drawer === "opportunities" ? "A1 模型机会池" : drawer === "model" ? "模型与数据证据" : "实时策略试算"}</h2>
                <p>{drawer === "opportunities" ? "A1触达评分用于机会排序；任一客户都可回到主工作台查看Top3，A2目标仅作为赛事正式提交标识。" : drawer === "model" ? "展示时间截断、模型指标和从数据到任务的形成过程。" : "调整模型与运营参数，观察当前客户Top3变化；不会覆盖已冻结策略或赛事提交文件。"}</p>
              </div>
              <button aria-label="关闭抽屉" onClick={() => setDrawer(null)}>×</button>
            </header>

            {drawer === "opportunities" && (
              <div className="opportunity-drawer-body">
                <div className="opportunity-toolbar">
                  <select aria-label="模型名单日期" value={rosterDate} onChange={(event) => setRosterDate(event.target.value)}>
                    {(rosterDates.length ? rosterDates : [{ date: "2026-04-15", scope: "submitted" }]).map((item) => <option key={item.date} value={item.date}>{item.date}{item.scope === "submitted" ? " · 提交版" : " · 历史回放"}</option>)}
                  </select>
                  <input value={rosterQuery} onChange={(event) => setRosterQuery(event.target.value)} placeholder="客户ID / 产品" />
                  <select aria-label="模型名单渠道" value={rosterChannel} onChange={(event) => setRosterChannel(event.target.value)}>
                    <option value="">全部渠道</option>
                    {Object.entries(channelNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <button onClick={applyRosterFilters}>应用筛选</button>
                </div>
                <div className="opportunity-table">
                  <table>
                    <thead><tr><th>客户与触达</th><th>目标产品</th><th>渠道</th><th>响应概率</th><th>策略覆盖</th><th /></tr></thead>
                    <tbody>
                      {roster.map((row) => (
                        <tr key={row.contact_id}>
                          <td><b>{row.customer_id}</b><small>{row.contact_id}{row.rank ? ` · 排名#${row.rank}` : " · A1评分记录"}</small></td>
                          <td><b>{row.product_name}</b><small>{row.product_id} · {row.risk_level}</small></td>
                          <td>{channelNames[row.channel]}</td>
                          <td><strong>{percent(row.response_prob)}</strong></td>
                          <td><Status warn={false}>{row.strategy_eligible ? "A2目标" : "全量客户"}</Status></td>
                          <td><button onClick={() => { setDrawer(null); void loadStrategies(row.customer_id); }}>查看Top3</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {rosterLoading && <div className="drawer-loading">正在加载模型名单…</div>}
                </div>
                <footer className="drawer-pagination"><span>共 {rosterTotal.toLocaleString()} 条触达预测</span><div><button disabled={rosterPage <= 1} onClick={() => void loadRoster(rosterPage - 1)}>上一页</button><b>{rosterPage} / {rosterPageCount}</b><button disabled={rosterPage >= rosterPageCount} onClick={() => void loadRoster(rosterPage + 1)}>下一页</button></div></footer>
              </div>
            )}

            {drawer === "model" && (
              <div className="model-proof-body">
                <div className="model-metrics-proof">
                  <article><small>AUC</small><strong>{summary?.model_metrics.auc?.toFixed(3) ?? "—"}</strong><span>排序区分能力</span></article>
                  <article><small>F1</small><strong>{summary?.model_metrics.best_f1?.toFixed(3) ?? "—"}</strong><span>最佳阈值效果</span></article>
                  <article><small>Lift@10%</small><strong>{summary?.model_metrics.lift_at_10_percent?.toFixed(2) ?? "—"}×</strong><span>高意向客户提升</span></article>
                </div>
                <div className="model-pipeline">
                  {[
                    ["ODS/DWD业务数据", "客户、产品、持仓、行为、历史触达"],
                    ["严格时间截断", "所有特征严格早于 contact_date / strategy_date"],
                    ["A1响应预测", "8000条触达记录生成认购概率"],
                    ["统一策略服务", "A2 2000人读取正式Top3，其余客户按需生成并冻结"],
                    ["客户经理任务", "策略下钻、联系执行、自动归因与KPI"],
                  ].map((item, index) => <article key={item[0]}><b>{index + 1}</b><span><strong>{item[0]}</strong><small>{item[1]}</small></span>{index < 4 && <i>→</i>}</article>)}
                </div>
                <div className="model-proof-note"><b>可复现证据</b><span>统一分析基准日 2026-03-31，策略日 2026-04-15，训练与推理共用特征工程，模型与特征版本随 ADS 结果留存。</span></div>
              </div>
            )}

            {drawer === "lab" && (
              <div className="lab-drawer-body">
                <div className="lab-controls">
                  <label>客户经理配额 <b>{quota}</b><input type="number" min="0" max="6000" step="100" value={quota} onChange={(event) => { generationRequestId.current += 1; setGenerating(false); setGenerated(null); setQuota(Number(event.target.value)); }} /></label>
                  <button disabled={generating || !strategyCustomerId} onClick={() => void regenerate()}>{generating ? "模型计算中…" : "运行实时策略"}</button>
                </div>
                {generated ? (
                  <div className="lab-compare">
                    <header><b>当前 Top3 vs 参数试算</b><Status>{generated.parameters.ranking_source === "ltr" ? "LTR排序" : "A1概率回退"}</Status></header>
                    {[1, 2, 3].map((rank) => {
                      const before = strategies.find((item) => item.rank === rank);
                      const after = generated.items.find((item) => item.rank === rank);
                      if (!after) return null;
                      const changed = before?.product_id !== after.product_id;
                      return <article key={rank}><b>TOP {rank}</b><span><small>当前快照</small><strong>{before ? `${before.product_id} ${before.product_name}` : "—"}</strong></span><i>→</i><span><small>参数试算</small><strong className={changed ? "changed" : ""}>{after.product_id} {after.product_name}</strong></span><em>{after.ltr_score != null ? after.ltr_score.toFixed(3) : percent(after.model_prob)}<small>{after.ltr_score != null ? "LTR分" : "A1概率"}</small></em></article>;
                    })}
                    <p>产品排序 = LTR 学习排序模型分（回退 A1 概率）；渠道、时段和话术再由规则引擎回验。</p>
                  </div>
                ) : <div className="lab-waiting"><b>等待运行策略试算</b><p>该能力用于现场展示运营参数变化如何驱动策略结果变化。</p></div>}
              </div>
            )}
          </section>
        </div>
      )}

      {showSimulation && selectedStrategy && (
        <div className="simulation-layer" role="dialog" aria-modal="true" aria-label="模拟新增持仓回流">
          <section className="simulation-dialog">
            <header><div><small>仅供答辩演示</small><h2>模拟核心业务系统回传新增持仓</h2></div><button onClick={() => setShowSimulation(false)}>×</button></header>
            <div className="simulation-product"><b>TOP {selectedStrategy.rank}</b><span><strong>{selectedStrategy.product_name}</strong><small>{selectedStrategy.product_id} · 将进入自动归因规则</small></span></div>
            <label>购买日期<input type="date" value={simulationDate} onChange={(event) => setSimulationDate(event.target.value)} /></label>
            <label>购买金额<input type="number" min="1" step="1000" value={simulationAmount} onChange={(event) => setSimulationAmount(Number(event.target.value))} /></label>
            <p>模拟记录只写入演示持仓表，不修改赛事原始持仓数据。命中Top3且处于30天窗口内时，客户经理KPI才会增加。</p>
            <footer><button onClick={() => setShowSimulation(false)}>取消</button><button className="primary" disabled={busy} onClick={() => void simulateHolding()}>{busy ? "正在归因…" : "确认回传并自动归因"}</button></footer>
          </section>
        </div>
      )}
    </section>
  );
}
