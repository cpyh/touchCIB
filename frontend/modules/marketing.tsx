"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "../shared/api";
import { channelNames, Status } from "../shared/ui";
import { formatNumber, formatTime, metric, money, percent } from "../shared/format";

type TaskStatus = "all" | "pending" | "follow_up" | "converted";
type WorkspaceMode = "all" | "manager";
type ManagerView = "today" | "pool";
type ManagerTab = ManagerView | "follow_up" | "converted";
type StrategyDetailTab = "why" | "compliance" | "script";
type DrillLayer = "a1" | "a2" | "strategy";
type ActionTab = "progress" | "attribution" | "lineage";
type Drawer = "opportunities" | "model" | "lab" | null;
type ToggleableConstraint =
  | "channel_app_requires_app"
  | "channel_call_complaint_block"
  | "aum_affordability";

const TASK_PAGE_SIZE = 12;
const ROSTER_PAGE_SIZE = 9;

const constraintOptions: Array<{
  id: ToggleableConstraint;
  label: string;
  description: string;
}> = [
  {
    id: "channel_app_requires_app",
    label: "App 安装限制",
    description: "关闭后，未安装 App 的客户也允许 app_push 参与 A1 渠道排序",
  },
  {
    id: "channel_call_complaint_block",
    label: "投诉外呼保护",
    description: "关闭后，近 90 天投诉客户也允许 call 参与 A1 渠道排序",
  },
  {
    id: "aum_affordability",
    label: "起投能力限制",
    description: "关闭后，不再用客户 AUM 过滤高起投门槛产品",
  },
];

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
  min_invest_affordable: "起投金额留痕",
  channel_app_requires_app: "App渠道资格",
  channel_call_complaint_block: "投诉与外呼限制",
  channel_manager_quota: "当日动态经理池",
  channel_manager_eligible: "经理池资格",
  slot_in_enum: "联系时段合规",
  script_length: "话术长度检查",
  script_compliance_note: "风险提示完整",
  script_overshoot_warning: "风险越级提示",
  aum_affordability: "起投金额能力",
};

interface MarketingTask {
  customer_id: string;
  risk_appetite: string;
  vip_level: string;
  aum: number;
  status: Exclude<TaskStatus, "all">;
  strategy_id: string | null;
  strategy_ready: boolean;
  strategy_source: "batch_generated" | "batch_pending";
  product_id: string | null;
  product_name: string | null;
  risk_level: string | null;
  expected_return: number | null;
  recommended_channel: string | null;
  recommended_time: string | null;
  response_prob: number | null;
  opportunity_score: number | null;
  opportunity_source: "ads_a1_batch" | "not_scored";
  model_contact_id: string | null;
  opportunity_product_id: string | null;
  opportunity_product_name: string | null;
  opportunity_channel: string | null;
  opportunity_date: string | null;
  manager_pool: boolean;
  manager_pool_rank: number | null;
  manager_today: boolean;
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
  model_prob?: number | null;
  a1_rank?: number;
  selection_reason?: string;
  model_version?: string;
  rule_version?: string;
  batch_id?: string;
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
  lift_vs_base?: number;
  explanation_scope?: "customer_product_channel" | string;
  explanation_method?: "tree_shap" | "linear_contribution" | string;
  local_factors?: PredictionFactor[];
  reasons: string[];
  warnings?: string[];
}

interface PredictionFactor {
  feature: string;
  label: string;
  direction: "positive" | "negative" | "neutral";
  contribution: number;
  reason: string;
}

interface GeneratedItem {
  rank: number;
  product_id: string;
  product_name: string;
  recommended_channel: string;
  model_prob: number;
}

interface GeneratedResult {
  customer_id: string;
  strategy_date: string;
  parameters: {
    manager_pool_size: number;
    manager_pool_effective: boolean;
    manager_daily_capacity: number;
    manager_eligible: boolean;
    manager_pool_member: boolean;
    manager_priority_score: number;
    manager_priority_rank: number | null;
    assigned_channel: string;
    channel_reason: string;
    top_n: number;
    disabled_constraints: ToggleableConstraint[];
    constraints: Record<ToggleableConstraint, boolean>;
    evaluated_channels: string[];
    baseline_channels: string[];
    a1_candidate_count: number;
    baseline_candidate_count: number;
    ranking_source?: string;
    a1_source?: string;
  };
  items: GeneratedItem[];
}

interface ManagerSummary {
  pool_total: number;
  pending: number;
  today_count: number;
  follow_up: number;
  converted: number;
  daily_capacity: number;
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
  businessDate: string;
  historical: boolean;
  initialCustomerId: string;
  initialCohort?: "all" | "expiry";
  onOpenCustomer: (customerId: string) => void;
  onOpenDashboard?: () => void;
  notify: (message: string) => void;
}

export function MarketingPage({
  businessDate,
  historical,
  initialCustomerId,
  initialCohort,
  onOpenCustomer,
  onOpenDashboard,
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
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("all");
  const [managerView, setManagerView] = useState<ManagerView>("today");
  const [managerTab, setManagerTab] = useState<ManagerTab>("today");
  const [managerSummary, setManagerSummary] = useState<ManagerSummary>({
    pool_total: 0,
    pending: 0,
    today_count: 0,
    follow_up: 0,
    converted: 0,
    daily_capacity: 12,
  });
  const [taskPage, setTaskPage] = useState(1);
  const [taskTotal, setTaskTotal] = useState(0);
  const [taskQuery, setTaskQuery] = useState("");
  const [taskLoading, setTaskLoading] = useState(false);
  const [taskPopulation, setTaskPopulation] = useState(8000);
  const [strategyReadyCount, setStrategyReadyCount] = useState(0);
  const [modelCoveredCustomers, setModelCoveredCustomers] = useState(0);
  const taskSearchTimer = useRef<number | null>(null);
  const taskRequestId = useRef(0);
  const rosterRequestId = useRef(0);
  const strategyRequestId = useRef(0);
  const evidenceRequestId = useRef(0);
  const generationRequestId = useRef(0);

  const [summary, setSummary] = useState<MarketingSummary | null>(null);
  const [strategyCustomerId, setStrategyCustomerId] = useState(initialCustomerId || "");
  const [strategyDate, setStrategyDate] = useState(businessDate);
  const [riskAppetite, setRiskAppetite] = useState("—");
  const [customerVipLevel, setCustomerVipLevel] = useState("—");
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [selectedOpportunity, setSelectedOpportunity] = useState<MarketingTask | null>(null);
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [selectedRank, setSelectedRank] = useState(1);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [detailTab, setDetailTab] = useState<StrategyDetailTab>("why");
  const [drillLayer, setDrillLayer] = useState<DrillLayer>("a1");
  const [expandedFactor, setExpandedFactor] = useState<number | null>(0);
  const [expandedRule, setExpandedRule] = useState<string | null>(null);
  const [actionTab, setActionTab] = useState<ActionTab>("progress");
  const [predictionEvidence, setPredictionEvidence] = useState<PredictionEvidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const [drawer, setDrawer] = useState<Drawer>(null);
  const [showSimulation, setShowSimulation] = useState(false);
  const [simulationAmount, setSimulationAmount] = useState(50000);
  const [lastSimulation, setLastSimulation] = useState<SimulatedHoldingResult | null>(null);

  const [roster, setRoster] = useState<RosterRow[]>([]);
  const [rosterTotal, setRosterTotal] = useState(0);
  const [rosterPage, setRosterPage] = useState(1);
  const [rosterQuery, setRosterQuery] = useState("");
  const [rosterChannel, setRosterChannel] = useState("");
  const [rosterLoading, setRosterLoading] = useState(false);
  const [appliedRosterFilters, setAppliedRosterFilters] = useState<RosterFilters>({
    date: businessDate,
    keyword: "",
    channel: "",
  });

  const [generated, setGenerated] = useState<GeneratedResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [labManagerPoolSize, setLabManagerPoolSize] = useState(200);
  const [labManagerDailyCapacity, setLabManagerDailyCapacity] = useState(12);
  const [constraintEnabled, setConstraintEnabled] = useState<
    Record<ToggleableConstraint, boolean>
  >({
    channel_app_requires_app: true,
    channel_call_complaint_block: true,
    aum_affordability: true,
  });

  useEffect(() => {
    void loadTasks(1, "all", "");
    void loadSummary();
    // 首次挂载只加载一次；后续刷新由筛选与业务动作显式触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [businessDate]);

  useEffect(() => {
    if (initialCohort && initialCohort !== taskCohort) {
      // Prop 驱动的跨页面跳转筛选需要在进入营销页时同步一次。
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTaskCohort(initialCohort);
      void loadTasks(1, taskStatus, taskQuery, initialCohort);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCohort]);

  useEffect(() => {
    if (initialCustomerId) void loadStrategies(initialCustomerId);
    // 跨页面传入的客户编号是唯一触发源，策略内部状态不应导致重复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setSummary(await api<MarketingSummary>(`/dashboard/summary?business_date=${encodeURIComponent(businessDate)}`));
    } catch (error) {
      notify(`经营指标加载失败：${(error as Error).message}`);
    }
  }

  async function loadTasks(
    page: number,
    status: TaskStatus = taskStatus,
    keyword: string = taskQuery,
    cohort: "all" | "expiry" = taskCohort,
    workspace: WorkspaceMode = workspaceMode,
    nextManagerView: ManagerView = managerView,
  ) {
    const requestId = ++taskRequestId.current;
    setTaskLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        size: String(TASK_PAGE_SIZE),
        status,
        cohort,
        workspace,
        manager_view: nextManagerView,
        manager_daily_capacity: String(managerSummary.daily_capacity),
        business_date: businessDate,
      });
      if (keyword.trim()) params.set("keyword", keyword.trim());
      const data = await api<{
        total: number;
        population_total: number;
        strategy_ready_customers: number;
        model_covered_customers: number;
        counts: Record<TaskStatus, number>;
        manager_summary: ManagerSummary;
        tasks: MarketingTask[];
      }>(`/marketing/tasks?${params.toString()}`);
      if (requestId !== taskRequestId.current) return;
      if (page > 1 && data.total > 0 && data.tasks.length === 0) {
        void loadTasks(
          Math.ceil(data.total / TASK_PAGE_SIZE),
          status,
          keyword,
          cohort,
          workspace,
          nextManagerView,
        );
        return;
      }
      setTasks(data.tasks);
      setTaskTotal(data.total);
      setTaskCounts(data.counts);
      setManagerSummary(data.manager_summary);
      setTaskPopulation(data.population_total);
      setStrategyReadyCount(data.strategy_ready_customers);
      setModelCoveredCustomers(data.model_covered_customers);
      setTaskPage(page);
      setTaskStatus(status);
      setTaskCohort(cohort);
      setWorkspaceMode(workspace);
      setManagerView(nextManagerView);
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

  function changeWorkspace(mode: WorkspaceMode) {
    if (taskSearchTimer.current) window.clearTimeout(taskSearchTimer.current);
    const nextStatus: TaskStatus = mode === "manager" ? "pending" : "all";
    setWorkspaceMode(mode);
    setTaskStatus(nextStatus);
    setTaskCohort("all");
    setManagerTab("today");
    setManagerView("today");
    void loadTasks(1, nextStatus, taskQuery, "all", mode, "today");
  }

  function changeManagerTab(tab: ManagerTab) {
    const nextStatus: TaskStatus = tab === "today" || tab === "pool" ? "pending" : tab;
    const nextView: ManagerView = tab === "pool" ? "pool" : "today";
    setManagerTab(tab);
    setTaskStatus(nextStatus);
    setManagerView(nextView);
    void loadTasks(1, nextStatus, taskQuery, "all", "manager", nextView);
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
        `/campaign/events?customer_id=${encodeURIComponent(customerId)}&business_date=${encodeURIComponent(businessDate)}`,
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
    setStrategies([]);
    setEvents([]);
    setPredictionEvidence(null);
    setEvidenceLoading(false);
    setSelectedOpportunity(currentOpportunity);
    setRiskAppetite(currentOpportunity?.risk_appetite ?? "—");
    setCustomerVipLevel(currentOpportunity?.vip_level ?? "客户");
    setBusy(true);
    try {
      const data = await api<{
        customer_id: string;
        strategy_date: string;
        strategy_source: "warehouse_batch";
        risk_appetite: string;
        vip_level: string;
        aum: number;
        items: StrategyItem[];
      }>(`/customers/${encodeURIComponent(normalized)}/strategies?business_date=${encodeURIComponent(businessDate)}`);
      if (requestId !== strategyRequestId.current) return;
      const next =
        data.items.find((item) => item.rank === preferredRank)
        ?? data.items.find((item) => item.status === "已响应")
        ?? data.items.find((item) => item.status === "已触达")
        ?? data.items.find((item) => item.status === "待执行")
        ?? data.items[0];
      setStrategyCustomerId(normalized);
      setStrategyDate(data.strategy_date);
      setRiskAppetite(data.risk_appetite);
      setCustomerVipLevel(data.vip_level);
      setStrategies(data.items);
      setSelectedRank(next?.rank ?? 1);
      setDetailTab("why");
      setDrillLayer("a1");
      setExpandedFactor(0);
      setExpandedRule(null);
      setActionTab("progress");
      setLastSimulation(null);
      setTasks((current) => current.map((task) => (
        task.customer_id === normalized
          ? {
              ...task,
              strategy_id: next?.strategy_id ?? task.strategy_id,
              strategy_ready: true,
              strategy_source: "batch_generated",
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
          strategy_source: "batch_generated",
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
    setDrillLayer("a1");
    setExpandedFactor(0);
    setExpandedRule(null);
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
          business_date: businessDate,
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
          buy_date: businessDate,
          amount: simulationAmount,
          business_date: businessDate,
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
      }>(`/marketing/roster?${params.toString()}`);
      if (requestId !== rosterRequestId.current) return;
      setRoster(data.customers);
      setRosterTotal(data.total);
      setRosterPage(page);
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
      date: businessDate,
      keyword: rosterQuery,
      channel: rosterChannel,
    };
    setAppliedRosterFilters(filters);
    setDrawer("opportunities");
    void loadRoster(1, filters);
  }

  function applyRosterFilters() {
    const filters = {
      date: businessDate,
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
          business_date: businessDate,
          manager_pool_size: labManagerPoolSize,
          manager_daily_capacity: labManagerDailyCapacity,
          disabled_constraints: constraintOptions
            .filter((option) => !constraintEnabled[option.id])
            .map((option) => option.id),
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

  function toggleConstraint(id: ToggleableConstraint) {
    generationRequestId.current += 1;
    setGenerating(false);
    setGenerated(null);
    setConstraintEnabled((current) => ({ ...current, [id]: !current[id] }));
  }

  function changeLabCapacity(kind: "pool" | "daily", value: number) {
    generationRequestId.current += 1;
    setGenerated(null);
    if (kind === "pool") setLabManagerPoolSize(Math.max(0, Math.min(8000, value)));
    else setLabManagerDailyCapacity(Math.max(1, Math.min(100, value)));
  }

  const selectedStrategy =
    strategies.find((item) => item.rank === selectedRank) ?? strategies[0];
  const generatedTop3ChangeCount = generated
    ? generated.items.filter((after) => {
      const before = strategies.find((item) => item.rank === after.rank);
      return before?.product_id !== after.product_id
        || before?.recommended_channel !== after.recommended_channel;
    }).length
    : 0;
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
  const localFactors: PredictionFactor[] = predictionEvidence?.local_factors?.length
    ? predictionEvidence.local_factors
    : (predictionEvidence?.reasons ?? [])
      .filter((reason) => !reason.includes("全局重要性") && !reason.includes("模型整体"))
      .map((reason, index) => ({
        feature: `factor_${index + 1}`,
        label: reason.split("：")[0] || `影响因子 ${index + 1}`,
        direction: reason.includes("降低") ? "negative" : reason.includes("提升") ? "positive" : "neutral",
        contribution: 0,
        reason,
      }));
  // 下钻主概率必须与日批排名同口径；在线说明只补充因子。
  const selectedA1Probability = selectedStrategy?.model_prob ?? predictionEvidence?.probability;
  const explanationMethod = predictionEvidence?.explanation_method === "tree_shap"
    ? "TreeSHAP 单次贡献"
    : predictionEvidence?.explanation_method === "linear_contribution"
      ? "线性模型单次贡献"
      : "当前请求局部解释";

  return (
    <section className="manager-marketing-shell">
      <header className="manager-marketing-head">
        <div className="manager-title">
          <small>今日客户运营 · 客户经理 MGR001</small>
          <h1>营销运营工作台</h1>
          <p>优先处理高机会客户，完成策略选择、客户触达与转化追踪。</p>
        </div>
        <div className="manager-kpis">
          {workspaceMode === "manager" ? (
            <>
              <div><small>高价值经理池</small><strong>{formatNumber(managerSummary.pool_total)}</strong><span>每日随最新画像动态重算</span></div>
              <div><small>今日任务</small><strong>{formatNumber(managerSummary.today_count)}<i>/ {formatNumber(managerSummary.daily_capacity)}</i></strong><span>按机会分滚动补位</span></div>
              <div><small>等待回流</small><strong>{formatNumber(managerSummary.follow_up)}</strong><span>已联系，等待购买回流</span></div>
              <div className="target"><small>经理池已转化</small><strong>{formatNumber(managerSummary.converted)}</strong><span>购买事实自动归因</span></div>
            </>
          ) : (
            <>
              <div><small>客户池</small><strong>{formatNumber(taskPopulation)}</strong><span>覆盖全部可运营客户</span></div>
              <div><small>高机会覆盖</small><strong>{formatNumber(modelCoveredCustomers)}</strong><span>A1 已完成机会评分</span></div>
              <div><small>已转化</small><strong>{eventServiceAvailable ? formatNumber(summary?.events.responded_customers ?? summary?.events.responded) : "—"}</strong><span>{eventServiceAvailable ? "购买回流自动归因" : "事件服务暂不可用"}</span></div>
              <div className="target"><small>本月目标</small><strong>{eventServiceAvailable ? formatNumber(managerKpi?.actual) : "—"}<i>/ {formatNumber(managerKpi?.target ?? 30)}</i></strong><span>数仓策略已就绪 {formatNumber(strategyReadyCount)} 人</span></div>
            </>
          )}
        </div>
        <div className="manager-head-actions">
          <button onClick={openOpportunityPool}><b>机会客户池</b><i>›</i></button>
          <button onClick={() => setDrawer("model")}><b>模型与数据证据</b><i>›</i></button>
          {onOpenDashboard && (
            <button onClick={onOpenDashboard}><b>去看板复盘</b><i>›</i></button>
          )}
        </div>
      </header>
      {historical && <div className="historical-snapshot-note"><b>{businessDate} 历史快照</b><span>客户、机会和策略均按该日口径展示；触达、归因和实时策略操作已锁定。</span></div>}

      <nav className="marketing-workspace-mode" aria-label="营销工作台模式">
        <button className={workspaceMode === "all" ? "on" : ""} onClick={() => changeWorkspace("all")}>
          <b>全渠道运营</b><span>覆盖 App、电话、短信与经理渠道</span>
        </button>
        <button className={workspaceMode === "manager" ? "on" : ""} onClick={() => changeWorkspace("manager")}>
          <b>经理 VIP 通道</b><span>Top200 动态池 · 今日最多 12 人</span>
        </button>
      </nav>

      <div className="manager-workspace">
        <aside className="task-pane">
          <header>
            <div><small>{workspaceMode === "manager" ? "高价值专属通道" : "客户机会"}</small><h2>{workspaceMode === "manager" ? "客户经理渠道池" : "全量客户队列"}</h2></div>
            <Status>{taskLoading ? "更新中" : `${formatNumber(taskTotal)} 人`}</Status>
          </header>
          {workspaceMode === "manager" ? (
            <>
              <nav className="task-status-tabs manager-tabs">
                {([
                  ["today", "今日任务", managerSummary.today_count],
                  ["pool", "候选池", managerSummary.pending],
                  ["follow_up", "等待回流", managerSummary.follow_up],
                  ["converted", "已转化", managerSummary.converted],
                ] as Array<[ManagerTab, string, number]>).map(([tab, label, count]) => (
                  <button className={managerTab === tab ? "on" : ""} key={tab} onClick={() => changeManagerTab(tab)}>
                    <span>{label}</span><b>{formatNumber(count)}</b>
                  </button>
                ))}
              </nav>
              <div className="manager-pool-note"><b>每日动态重算</b><span>未处理客户次日随新预测继续入池并重新排序，不做超时释放。</span></div>
            </>
          ) : (
            <>
              <nav className="task-status-tabs">
                {(Object.keys(taskStatusNames) as TaskStatus[]).map((status) => (
                  <button className={taskStatus === status ? "on" : ""} key={status} onClick={() => changeTaskStatus(status)}>
                    <span>{taskStatusNames[status]}</span><b>{formatNumber(taskCounts[status])}</b>
                  </button>
                ))}
              </nav>
              <div className="task-cohort">
                <button className={taskCohort === "all" ? "on" : ""} onClick={() => changeTaskCohort("all")}>全部客户</button>
                <button className={taskCohort === "expiry" ? "on" : ""} onClick={() => changeTaskCohort("expiry")}>到期跟进</button>
              </div>
            </>
          )}
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
              const executionChannel = task.recommended_channel
                ? channelNames[task.recommended_channel]
                : "暂无A1触达";
              return (
                <button
                  className={strategyCustomerId === task.customer_id ? "task-card selected" : "task-card"}
                  disabled={busy || !task.strategy_ready}
                  key={task.customer_id}
                  onClick={() => void loadStrategies(task.customer_id, undefined, task)}
                >
                  <span className="task-card-head">
                    <b>{task.customer_id}</b>
                    <span className="task-card-badges">
                      {task.strategy_ready && <em className="ready">Top3就绪</em>}
                      {task.manager_today && <em className="manager-today">今日</em>}
                      {task.manager_pool && !task.manager_today && <em className="manager-pool">经理池</em>}
                      {!task.strategy_ready && <em className="a2">待跑批</em>}
                      <em className={task.status}>{taskStatusNames[task.status]}</em>
                    </span>
                  </span>
                  <span className="task-card-opportunity">
                    <span>
                      <small>首选机会</small>
                      <strong>{task.opportunity_product_name ?? "等待下次日批"}</strong>
                    </span>
                    <em className={task.opportunity_score == null ? "live" : ""}>
                      <b>{task.opportunity_score == null ? "待评分" : percent(task.opportunity_score)}</b>
                      <small>{task.opportunity_score == null ? "日批" : "机会分"}</small>
                    </em>
                  </span>
                  <small className="task-card-meta">{task.vip_level} · {task.risk_appetite} · {executionChannel}{task.manager_pool_rank ? ` · 池内 #${task.manager_pool_rank}` : ""}</small>
                  <span className="task-signal">
                    <i><b style={{ width: `${(task.opportunity_score ?? 0) * 100}%` }} /></i>
                    <em>{task.opportunity_score == null ? "等待策略批处理覆盖" : "A1 客户最高机会"}</em>
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
                  <i className="official">
                    全量客户 · 数仓日批Top3
                  </i>
                )}
                当前客户
              </small>
              <strong>{strategyCustomerId || "请选择左侧客户任务"}</strong>
              <em>{strategyCustomerId ? `${selectedTask?.vip_level ?? customerVipLevel} · 风险偏好 ${riskAppetite} · 策略批次 ${strategyDate}` : "按客户最高机会分排序，点击后查看Top3"}</em>
            </span>
            <div className="customer-context-actions">
              <button disabled={!strategyCustomerId || busy} onClick={() => onOpenCustomer(strategyCustomerId)}>查看画像</button>
              <button disabled={historical || !strategyCustomerId || busy} className="lab" title={historical ? "历史快照只读" : undefined} onClick={() => setDrawer("lab")}>策略试算</button>
            </div>
          </header>

          {strategyLoading ? (
            <div className="strategy-loading-new">
              <i />
              <b>正在加载数仓 Top3</b>
              <p>读取所选业务日的A1评分、A2基础规则轨迹与最终执行策略。</p>
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
                    <small>数仓日批策略 · TOP {selectedStrategy.rank}</small>
                    <h2>{selectedStrategy.product_name}</h2>
                    <p>{selectedStrategy.product_type ?? "财富产品"} · 风险 {selectedStrategy.risk_level} · 预期年化 {percent(selectedStrategy.expected_return)}</p>
                  </div>
                  <div className="strategy-route">
                    <span><small>建议渠道</small><b>{channelNames[selectedStrategy.recommended_channel]}</b></span>
                    <span><small>最佳时段</small><b>{selectedStrategy.recommended_time}</b></span>
                  </div>
                </header>

                <nav className="strategy-detail-tabs">
                  <button className={detailTab === "why" ? "on" : ""} onClick={() => setDetailTab("why")}>策略下钻</button>
                  <button className={detailTab === "compliance" ? "on" : ""} onClick={() => setDetailTab("compliance")}>合规检查 <i>{selectedPassedRules.length}/{selectedStrategy.rule_trace.length}</i></button>
                  <button className={detailTab === "script" ? "on" : ""} onClick={() => setDetailTab("script")}>执行话术</button>
                </nav>

                <div className="strategy-detail-body">
                  {detailTab === "why" && (
                    <div className="why-view">
                      <nav className="drill-stepper" aria-label="策略形成过程">
                        <button className={drillLayer === "a1" ? "on" : ""} onClick={() => setDrillLayer("a1")}>
                          <i>1</i><span><small>A1 意愿预测</small><strong>{evidenceLoading ? "计算中" : selectedA1Probability != null ? percent(selectedA1Probability) : "待复核"}</strong></span>
                        </button>
                        <b>›</b>
                        <button className={drillLayer === "a2" ? "on" : ""} onClick={() => setDrillLayer("a2")}>
                          <i>2</i><span><small>A2 规则筛选</small><strong>{selectedFailedRules.length ? "需复核" : `${selectedPassedRules.length} 项通过`}</strong></span>
                        </button>
                        <b>›</b>
                        <button className={drillLayer === "strategy" ? "on" : ""} onClick={() => setDrillLayer("strategy")}>
                          <i>3</i><span><small>形成可执行策略</small><strong>TOP {selectedStrategy.rank}</strong></span>
                        </button>
                      </nav>

                      {drillLayer === "a1" && (
                        <section className="drill-panel a1-drill">
                          <header className="drill-panel-head">
                            <div><small>客户 × 产品 × 渠道</small><h3>这一次预测为什么得到这个概率</h3><p>以下只解释当前客户与当前产品的本次预测，不是全局模型重要性。</p></div>
                            <aside><strong>{evidenceLoading ? "…" : selectedA1Probability != null ? percent(selectedA1Probability) : "—"}</strong><span>{predictionEvidence?.decision_label ?? "等待 A1 在线复核"}</span></aside>
                          </header>
                          {evidenceLoading ? (
                            <div className="factor-loading">正在按 {strategyDate} 的 as-of 口径生成单客户局部解释…</div>
                          ) : localFactors.length ? (
                            <div className="local-factor-list">
                              <header><span>本次预测的主要影响因子</span><small>{explanationMethod} · 点击查看关系</small></header>
                              {localFactors.map((factor, index) => (
                                <button
                                  className={`${factor.direction} ${expandedFactor === index ? "expanded" : ""}`}
                                  key={`${factor.feature}-${index}`}
                                  onClick={() => setExpandedFactor(expandedFactor === index ? null : index)}
                                >
                                  <i>{factor.direction === "positive" ? "↑" : factor.direction === "negative" ? "↓" : "·"}</i>
                                  <span><strong>{factor.label}</strong><small>{expandedFactor === index ? factor.reason : "点击查看该因子与本次推荐的关系"}</small></span>
                                  <em>{factor.contribution ? `${factor.contribution > 0 ? "+" : ""}${factor.contribution.toFixed(3)}` : "查看"}</em>
                                </button>
                              ))}
                            </div>
                          ) : (
                            <div className="factor-empty">A1 局部解释暂不可用；概率结果仍可用于排序，但不展示无法核验的归因。</div>
                          )}
                          {predictionEvidence?.warnings?.map((warning) => <p className="prediction-warning" key={warning}>{warning}</p>)}
                        </section>
                      )}

                      {drillLayer === "a2" && (
                        <section className="drill-panel a2-drill">
                          <header className="drill-panel-head">
                            <div><small>A1 排序结果 → A2 业务约束</small><h3>高概率不等于可以直接联系</h3><p>A2 不重复预测意愿，而是在 A1 优先级基础上检查风险、准入、渠道、时段与话术限制。</p></div>
                            <aside className={selectedFailedRules.length ? "warn" : "pass"}><strong>{selectedPassedRules.length}/{selectedStrategy.rule_trace.length}</strong><span>{selectedFailedRules.length ? "需要人工复核" : "当前策略可执行"}</span></aside>
                          </header>
                          <div className="a2-summary-flow">
                            <span><small>A1 原始排名</small><b>#{selectedStrategy.a1_rank ?? "—"} · {selectedA1Probability != null ? percent(selectedA1Probability) : "—"}</b></span>
                            <i>规则过滤</i>
                            <span><small>A2 保留结果</small><b>TOP {selectedStrategy.rank}</b></span>
                          </div>
                          {selectedStrategy.selection_reason && <p className="prediction-warning">{selectedStrategy.selection_reason}</p>}
                          <div className="rule-drill-list">
                            <header><span>当前策略的规则证据</span><small>点击规则查看判断依据</small></header>
                            {selectedStrategy.rule_trace.map((rule) => (
                              <button
                                className={`${rule.passed ? "passed" : "failed"} ${expandedRule === rule.rule_id ? "expanded" : ""}`}
                                key={rule.rule_id}
                                onClick={() => setExpandedRule(expandedRule === rule.rule_id ? null : rule.rule_id)}
                              >
                                <i>{rule.passed ? "✓" : "!"}</i>
                                <span><strong>{ruleNames[rule.rule_id] ?? rule.rule_id}</strong><small>{expandedRule === rule.rule_id ? rule.reason : "查看本客户与本策略的规则判断"}</small></span>
                                <em>{rule.passed ? "通过" : "复核"}</em>
                              </button>
                            ))}
                          </div>
                          <button className="drill-link" onClick={() => setDetailTab("compliance")}>查看全部合规证据与执行状态</button>
                        </section>
                      )}

                      {drillLayer === "strategy" && (
                        <section className="drill-panel strategy-drill">
                          <header className="drill-panel-head">
                            <div><small>模型信号与规则证据汇合</small><h3>客户经理最终应该怎么做</h3><p>把“推荐什么”与“怎么联系”放在同一条可执行路径中。</p></div>
                            <aside className="pass"><strong>TOP {selectedStrategy.rank}</strong><span>{selectedFailedRules.length ? "执行前需复核" : "可进入触达"}</span></aside>
                          </header>
                          <div className="strategy-relationship">
                            <article><small>客户</small><strong>{strategyCustomerId}</strong><span>{customerVipLevel} · 风险偏好 {riskAppetite}</span></article>
                            <i>匹配</i>
                            <article><small>产品</small><strong>{selectedStrategy.product_name}</strong><span>{selectedStrategy.risk_level} · 年化 {percent(selectedStrategy.expected_return)}</span></article>
                            <i>执行</i>
                            <article><small>触达</small><strong>{channelNames[selectedStrategy.recommended_channel]}</strong><span>{selectedStrategy.recommended_time}</span></article>
                          </div>
                          <div className="manager-conclusion">
                            <b>给客户经理的一句话</b>
                            <p>{riskReason ?? `客户风险偏好为 ${riskAppetite}，当前产品风险等级为 ${selectedStrategy.risk_level}`}；A1 对本次组合的响应倾向为 {selectedA1Probability != null ? percent(selectedA1Probability) : "待在线复核"}，建议在 {selectedStrategy.recommended_time} 通过{channelNames[selectedStrategy.recommended_channel]}完成联系。</p>
                          </div>
                          <div className="strategy-drill-actions">
                            <button onClick={() => setDetailTab("script")}>查看并复制执行话术</button>
                            <button onClick={() => setDetailTab("compliance")}>复核规则证据</button>
                          </div>
                        </section>
                      )}
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
            <div className="strategy-empty-new"><b>先从左侧选择一位高机会客户</b><p>系统会读取 {businessDate} 的数仓日批 Top3 与规则轨迹，再由客户经理选择一条策略执行联系。</p></div>
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
                          disabled={historical || busy || selectedStrategy.execution_enabled === false || selectedFailedRules.length > 0}
                          onClick={() => void completeContact()}
                        >
                          {busy ? "处理中…" : `采用 TOP ${selectedStrategy.rank} 并完成联系`}
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
                          <button disabled={historical} onClick={() => setShowSimulation(true)}>模拟系统收到新增持仓</button>
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
                      ["A1全量评分", "ads_a1_customer_product_score · 客户×产品"],
                      ["A2规则决策", "ads_a2_candidate_decision · 通过/过滤证据"],
                      ["可执行Top3", "ads_marketing_strategy · 日批策略"],
                      ["客户联系事实", "app_campaign_event · sent"],
                      ["新增持仓回流", "t_holding（生产）/ app_demo_holding（演示）"],
                      ["自动响应归因", "app_campaign_event · responded"],
                      ["经营指标更新", "dashboard · KPI重新聚合"],
                    ].map((item, index, lineage) => (
                      <div className="lineage-node" key={item[0]}><i>{index + 1}</i><span><b>{item[0]}</b><small>{item[1]}</small></span>{index < lineage.length - 1 && <em>↓</em>}</div>
                    ))}
                  </div>
                )}
              </div>

              <div className={lastSimulation?.kpi_delta.manager_conversion ? "personal-kpi changed" : "personal-kpi"}>
                <span><small>我的本月转化</small><strong>{eventServiceAvailable ? formatNumber(managerKpi?.actual) : "—"} / {formatNumber(managerKpi?.target ?? 30)}</strong></span>
                <i><b style={{ width: `${eventServiceAvailable ? Math.min(100, ((managerKpi?.actual ?? 0) / (managerKpi?.target ?? 30)) * 100) : 0}%` }} /></i>
                <em>{lastSimulation?.kpi_delta.manager_conversion ? "本次归因 +1" : eventServiceAvailable ? `完成率 ${percent((managerKpi?.actual ?? 0) / (managerKpi?.target ?? 30), 0)}` : "事件服务暂不可用"}</em>
              </div>
            </>
          )}
          {!selectedStrategy && (
            <div className="action-empty">
              <i>1</i>
              <b>先选择客户与策略</b>
              <p>左侧选择客户，中间确认 Top3 推荐后，这里会给出唯一的下一步行动。</p>
            </div>
          )}
        </aside>
      </div>

      {drawer && (
        <div className="marketing-drawer-layer" role="dialog" aria-modal="true">
          <section className={`marketing-drawer ${drawer}`}>
            <header>
              <div>
                <small>评委验收与高级能力</small>
                <h2>{drawer === "opportunities" ? "A1 模型机会池" : drawer === "model" ? "模型与数据证据" : "约束对照试算"}</h2>
                <p>{drawer === "opportunities" ? `查看 ${businessDate} A1日批的客户产品机会，并查看候选是否通过A2基础规则。` : drawer === "model" ? "展示时间截断、模型指标和从数据到任务的形成过程。" : "调整运营参数，现场试算A1排名和规则过滤后Top3；不覆盖ADS日批。"}</p>
              </div>
              <button aria-label="关闭抽屉" onClick={() => setDrawer(null)}>×</button>
            </header>

            {drawer === "opportunities" && (
              <div className="opportunity-drawer-body">
                <div className="opportunity-toolbar">
                  <span className="roster-business-date"><small>业务日期</small><b>{businessDate}</b></span>
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
                          <td><Status warn={!row.strategy_eligible}>{row.strategy_eligible ? "规则通过" : "已过滤"}</Status></td>
                          <td><button onClick={() => { setDrawer(null); void loadStrategies(row.customer_id); }}>查看Top3</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {rosterLoading && <div className="drawer-loading">正在加载模型名单…</div>}
                </div>
                <footer className="drawer-pagination"><span>共 {formatNumber(rosterTotal)} 条触达预测</span><div><button disabled={rosterPage <= 1} onClick={() => void loadRoster(rosterPage - 1)}>上一页</button><b>{formatNumber(rosterPage)} / {formatNumber(rosterPageCount)}</b><button disabled={rosterPage >= rosterPageCount} onClick={() => void loadRoster(rosterPage + 1)}>下一页</button></div></footer>
              </div>
            )}

            {drawer === "model" && (
              <div className="model-proof-body">
                <div className="model-metrics-proof">
                  <article><small>AUC</small><strong>{metric(summary?.model_metrics.auc, 3)}</strong><span>排序区分能力</span></article>
                  <article><small>F1</small><strong>{metric(summary?.model_metrics.best_f1, 3)}</strong><span>最佳阈值效果</span></article>
                  <article><small>Lift@10%</small><strong>{metric(summary?.model_metrics.lift_at_10_percent, 2)}×</strong><span>高意向客户提升</span></article>
                </div>
                <div className="model-pipeline">
                  {[
                    ["ODS/DWD业务数据", "客户、产品、持仓、行为、历史触达"],
                    ["严格时间截断", "所有特征严格早于 contact_date / strategy_date"],
                    ["A1 响应预测", "全量客户×30产品×可执行渠道生成响应概率与排名"],
                    ["A2 基础规则", "按风险、产品准入、客户状态与起投能力过滤"],
                    ["客户经理任务", "策略下钻、联系执行、自动归因与KPI"],
                  ].map((item, index) => <article key={item[0]}><b>{index + 1}</b><span><strong>{item[0]}</strong><small>{item[1]}</small></span>{index < 4 && <i>→</i>}</article>)}
                </div>
                <div className="model-proof-note"><b>可复现证据</b><span>当前业务日期 {businessDate}；日批覆盖截至当日已注册的全部客户，训练与推理共用特征工程，模型与特征版本随 ADS 结果留存。</span></div>
              </div>
            )}

            {drawer === "lab" && (
              <div className="lab-drawer-body">
                <div className="lab-controls">
                  <div className="lab-policy-config">
                    <label><span>经理候选池规模</span><input type="number" min="0" max="8000" value={labManagerPoolSize} onChange={(event) => changeLabCapacity("pool", Number(event.target.value))} /><small>决定哪些客户使用 manager</small></label>
                    <label><span>经理每日处理容量</span><input type="number" min="1" max="100" value={labManagerDailyCapacity} onChange={(event) => changeLabCapacity("daily", Number(event.target.value))} /><small>只影响工作台今日任务数</small></label>
                  </div>
                  <div className="lab-constraint-list">
                    {constraintOptions.map((option) => (
                      <label className="lab-constraint" key={option.id}>
                        <input
                          type="checkbox"
                          checked={constraintEnabled[option.id]}
                          onChange={() => toggleConstraint(option.id)}
                        />
                        <span>
                          <b>{option.label}</b>
                          <small>{option.description}</small>
                        </span>
                        <em>{constraintEnabled[option.id] ? "生效" : "关闭"}</em>
                      </label>
                    ))}
                  </div>
                  <button disabled={historical || generating || !strategyCustomerId} onClick={() => void regenerate()}>{generating ? "模型计算中…" : "运行实时策略"}</button>
                </div>
                {generated ? (
                  <div className="lab-compare">
                    <header>
                      <b>正式约束 Top3 vs 开关试算</b>
                      <Status warn={generated.parameters.disabled_constraints.length > 0}>
                        {generated.parameters.disabled_constraints.length > 0
                          ? `关闭 ${generated.parameters.disabled_constraints.length} 项 · Top3 变化 ${generatedTop3ChangeCount} 条`
                          : "全部约束生效"}
                      </Status>
                    </header>
                    <div className="lab-manager-decision">
                      <span><small>经理池结果</small><b>{generated.parameters.manager_pool_member ? `已入池 #${generated.parameters.manager_priority_rank}` : "未入池"}</b></span>
                      <i>→</i>
                      <span><small>本次执行渠道</small><b>{channelNames[generated.parameters.assigned_channel] ?? generated.parameters.assigned_channel}</b></span>
                      <em>试算参数：候选池 {generated.parameters.manager_pool_size} 人、日容量 {generated.parameters.manager_daily_capacity} 人。{generated.parameters.channel_reason}</em>
                    </div>
                    <div className="lab-channel-space">
                      <b>正式候选</b>
                      <span>{generated.parameters.baseline_channels.map((channel) => (
                        <em key={channel}>{channelNames[channel] ?? channel}</em>
                      ))}</span>
                      <i>→</i>
                      <b>试算候选</b>
                      <span>{generated.parameters.evaluated_channels.map((channel) => (
                        <em key={channel}>{channelNames[channel] ?? channel}</em>
                      ))}</span>
                      <small>A1 候选 {generated.parameters.baseline_candidate_count} → {generated.parameters.a1_candidate_count}</small>
                    </div>
                    {[1, 2, 3].map((rank) => {
                      const before = strategies.find((item) => item.rank === rank);
                      const after = generated.items.find((item) => item.rank === rank);
                      if (!after) return null;
                      const changed = before?.product_id !== after.product_id
                        || before?.recommended_channel !== after.recommended_channel;
                      return <article key={rank}><b>TOP {rank}</b><span><small>正式日批</small><strong>{before ? `${before.product_id} ${before.product_name}` : "—"}</strong><small>{before ? channelNames[before.recommended_channel] : "—"}</small></span><i>→</i><span><small>约束试算</small><strong className={changed ? "changed" : ""}>{after.product_id} {after.product_name}</strong><small className={changed ? "changed" : ""}>{channelNames[after.recommended_channel] ?? after.recommended_channel}</small></span><em>{percent(after.model_prob)}<small>A1 概率</small></em></article>;
                    })}
                    <p>{generatedTop3ChangeCount > 0
                      ? `候选空间重算后有 ${generatedTop3ChangeCount} 条 Top3 产品或渠道发生变化。`
                      : generated.parameters.a1_candidate_count !== generated.parameters.baseline_candidate_count
                        ? "候选空间已经变化，但新增候选的 A1 概率不足以进入 Top3；这同样说明最终结果由模型排序决定。"
                        : "本次约束配置没有改变候选空间，Top3 与正式日批一致。"} 试算不写入正式 ADS。</p>
                  </div>
                ) : <div className="lab-waiting"><b>等待运行策略试算</b><p>可调整经理池规模和每日处理容量，观察客户是否进入经理渠道；产品 Top3 仍由 A1 排名决定。</p></div>}
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
            <label>购买日期<input type="date" value={businessDate} readOnly /></label>
            <label>购买金额<input type="number" min="1" step="1000" value={simulationAmount} onChange={(event) => setSimulationAmount(Number(event.target.value))} /></label>
            <p>模拟记录按当前业务日回流，只写入演示持仓表，不修改赛事原始持仓数据。命中 Top3 且处于 30 天窗口内时，客户经理 KPI 才会增加。</p>
            <footer><button onClick={() => setShowSimulation(false)}>取消</button><button className="primary" disabled={historical || busy} onClick={() => void simulateHolding()}>{busy ? "正在归因…" : "确认回传并自动归因"}</button></footer>
          </section>
        </div>
      )}
    </section>
  );
}
