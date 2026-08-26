export const DASHBOARD_API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5001"
).replace(/\/$/, "");

export type DataStatus = "READY" | "NOT_READY" | "INVALID" | "NOT_STARTED";

interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T | null;
}

export interface DashboardOverview {
  generated_at: string;
  business_metrics: {
    customer_count: number;
    total_aum: number;
    product_count: number;
    total_holding_amount: number;
    currency: string;
    historical_contact_count: number;
    historical_response_rate: number;
    marketing_status: DataStatus;
  };
  risk_distribution: Array<{
    risk_level: string;
    risk_label: string;
    count: number;
  }>;
  holding_distribution: Array<{
    product_type: string;
    holding_amount: number;
    ratio: number | null;
  }>;
  a1_performance: {
    status: DataStatus;
    data_source?: string;
    metric_scope?: string;
    auc: number | null;
    f1: number | null;
    lift_at_10: number | null;
    prediction_count?: number;
    mean_probability?: number | null;
    probability_distribution: Array<{ bucket: string; count: number }>;
  };
  a2_performance: {
    status: DataStatus;
    data_source?: string;
    metric_scope?: string;
    result_row_count?: number;
    target_customer_count: number;
    generated_customer_count: number;
    coverage_rate: number | null;
    hit_rate_at_3: number | null;
    rule_count?: number;
    channel_distribution: Array<{ channel: string; count: number }>;
    time_distribution?: Array<{ time_slot: string; count: number }>;
    validation?: Record<string, boolean>;
  };
  portfolio_summary?: {
    status: DataStatus;
    scenario_count: number;
    constraints_passed_count: number;
    allocation_row_count: number;
    total_utility: number | null;
    max_optimality_gap: number | null;
  };
  portfolio: PortfolioResult;
  marketing_funnel: {
    status: DataStatus;
    target_customer_count: number;
    generated_customer_count: number;
    contacted_customer_count: number;
    responded_customer_count: number;
    generated_strategy_count?: number;
    sent_strategy_count?: number;
    responded_strategy_count?: number;
  };
  action_items?: {
    conversion: {
      actual: number;
      target: number;
      gap: number;
      label: string;
    };
    touch: {
      sent_strategies: number;
      total_strategies: number;
      high_intent_untouched: number;
    };
    channel: {
      manager_sent: number;
      manager_responded: number;
      manager_response_rate: number | null;
      manager_target: number;
    };
  };
  expiry_warning?: {
    available: boolean;
    as_of: string;
    window_days: number;
    holding_count: number;
    customer_count: number;
    amount: number;
    items: Array<{
      customer_id: string;
      product_id: string;
      product_name: string;
      maturity_date: string;
      amount: number;
    }>;
  };
}

export interface PortfolioResult {
  status: DataStatus;
  data_source?: string;
  scenario_id: string | null;
  total_amount?: number | null;
  expected_return?: number | null;
  volatility?: number | null;
  utility?: number | null;
  cash_weight?: number | null;
  constraints_satisfied?: boolean | null;
  optimality_gap?: number | null;
  allocation_by_product_type: Array<{ product_type: string; weight: number }>;
  allocation_items: Array<{
    product_id: string;
    product_name: string;
    product_type: string;
    risk_level: string;
    weight: number;
    allocation_amount: number;
  }>;
}

export class DashboardApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "DashboardApiError";
  }
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${DASHBOARD_API_BASE_URL}${path}`, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new DashboardApiError(`无法连接可视化看板服务（${DASHBOARD_API_BASE_URL}）`, 0);
  }

  let envelope: ApiEnvelope<T>;
  try {
    envelope = await response.json() as ApiEnvelope<T>;
  } catch {
    throw new DashboardApiError("看板服务返回了无法识别的数据", response.status);
  }
  if (!response.ok || envelope.code !== 0 || envelope.data === null) {
    throw new DashboardApiError(envelope.message || "看板数据读取失败", response.status);
  }
  return envelope.data;
}

export function getDashboardOverview(scenarioId: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ scenario_id: scenarioId });
  return request<DashboardOverview>(`/api/v1/dashboard/overview?${query}`, signal);
}
