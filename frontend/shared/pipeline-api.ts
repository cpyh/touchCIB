import { API_BASE } from "./api";

export type PipelineStatus = "pending" | "running" | "success" | "failed" | "skipped";

export interface PipelineStageDefinition {
  stage_id: string;
  name: string;
  layer: string;
  description: string;
  output: string;
  depends_on: string[];
}

export interface PipelineDefinition {
  pipeline_id: string;
  name: string;
  schedule: string;
  default_business_date: string;
  dws_snapshot_date: string;
  stages: PipelineStageDefinition[];
}

export interface PipelineStageRun {
  stage_id: string;
  name: string;
  status: PipelineStatus;
  started_at: string | null;
  finished_at: string | null;
  error?: string;
  metrics?: {
    dws_customers: number;
    business_date: string;
    marketing_rows: number;
    marketing_customers: number;
    portfolio_scenarios: number;
  };
}

export interface PipelineRun {
  run_id: string;
  pipeline_id: string;
  trigger: "manual";
  business_date: string;
  status: Exclude<PipelineStatus, "pending" | "skipped">;
  current_stage: string | null;
  current_stages: string[];
  started_at: string;
  finished_at: string | null;
  error: string | null;
  stages: PipelineStageRun[];
  logs: string[];
}

export interface PipelineSnapshot {
  definition: PipelineDefinition;
  run: PipelineRun | null;
}

async function json<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body?.error || `数据任务请求失败（HTTP ${response.status}）`);
  }
  return body as T;
}

export async function getLatestPipelineRun(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE}/pipeline/runs/latest`, {
    headers: { Accept: "application/json" },
    signal,
  });
  return json<PipelineSnapshot>(response);
}

export async function startPipelineRun(businessDate: string) {
  const response = await fetch(`${API_BASE}/pipeline/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ business_date: businessDate }),
  });
  return json<{ run: PipelineRun }>(response);
}
