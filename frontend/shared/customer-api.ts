export const CUSTOMER_API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5001"
).replace(/\/$/, "");

export interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

export interface CustomerListItem {
  customer_id: string;
  age_group: string;
  city: string;
  occupation: string;
  income_level: string;
  register_date: string;
  aum: number;
  risk_appetite: string;
  risk_label: string;
  vip_level: string;
  has_app: boolean;
}

export interface CustomerListData {
  items: CustomerListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface Holding {
  holding_id: string;
  product_id: string;
  product_name: string;
  product_type: string;
  risk_level: string;
  liquidity: string;
  amount: number;
  buy_date: string;
  expected_return: number;
}

export interface DistributionItem {
  name: string;
  amount: number;
  ratio: number | null;
}

export interface AiAnalysis {
  overview: string;
  insight: string;
  suggestion: string;
  highlights: string[];
}

export interface CustomerProfile {
  as_of_date: string;
  basic_info: CustomerListItem;
  asset_profile: {
    aum: number;
    holding_amount: number;
    holding_product_count: number;
    product_type_distribution: DistributionItem[];
    risk_distribution: DistributionItem[];
    high_liquidity_ratio: number | null;
    weighted_expected_return: number | null;
    holdings: Holding[];
  };
  behavior_profile: {
    total_counts: Record<"login" | "consult" | "complaint", number>;
    recent_30d_counts: Record<"login" | "consult" | "complaint", number>;
    latest_event_type: string | null;
    latest_event_date: string | null;
    tags: string[];
  };
  campaign_summary?: {
    contact_count: number;
    responded_count: number;
    response_rate: number | null;
    last_contact_date: string | null;
  };
  ai_summary: AiAnalysis | null;
  ai_summary_generated_at: string | null;
}

export interface CustomerCreatePayload {
  age_group: string;
  city: string;
  occupation: string;
  income_level: string;
  register_date: string;
  aum: number;
  vip_level: string;
  has_app: boolean;
}

export interface AiSummaryData {
  customer_id: string;
  analysis: AiAnalysis;
  generated_at: string;
  provider: string;
  model: string;
}

export class CustomerApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "CustomerApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${CUSTOMER_API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new CustomerApiError(
      `无法连接客户画像服务（${CUSTOMER_API_BASE_URL}）`,
      0,
    );
  }

  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new CustomerApiError("服务返回了无法识别的数据", response.status);
  }

  if (!response.ok || envelope.code !== 0) {
    throw new CustomerApiError(envelope.message || "请求失败", response.status);
  }
  return envelope.data;
}

export function listCustomers(
  params: {
    page: number;
    pageSize: number;
    keyword?: string;
    riskAppetite?: string;
    vipLevel?: string;
    city?: string;
  },
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
  });
  if (params.keyword) query.set("keyword", params.keyword);
  if (params.riskAppetite) query.set("risk_appetite", params.riskAppetite);
  if (params.vipLevel) query.set("vip_level", params.vipLevel);
  if (params.city) query.set("city", params.city);
  return request<CustomerListData>(`/api/v1/customers?${query}`, { signal });
}

export function getCustomerProfile(customerId: string, signal?: AbortSignal) {
  return request<CustomerProfile>(
    `/api/v1/customers/${encodeURIComponent(customerId)}/profile`,
    { signal },
  );
}

export function createCustomer(payload: CustomerCreatePayload) {
  return request<CustomerListItem>("/api/v1/customers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateAiSummary(customerId: string) {
  return request<AiSummaryData>(
    `/api/v1/customers/${encodeURIComponent(customerId)}/ai-summary`,
    { method: "POST" },
  );
}
