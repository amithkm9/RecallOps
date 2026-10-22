import { useQuery } from "@tanstack/react-query";
export type Mode = "replay" | "live";
export interface Recall {
  id: string;
  source_id: string;
  product_name: string;
  brand: string;
  source_url: string;
  published_at: string;
  ingested_at: string;
  clock_warnings?: string[];
  version_id: string;
  official_version: string;
  reason: string;
  risk: string;
  raw: Record<string, unknown>;
}
export interface Inventory {
  id: string;
  sku: string;
  product_name: string;
  gtin: string;
  lot: string | null;
  quantity: number;
  supplier: string;
  expires_on: string | null;
  status: string;
  store_id: string;
}
export interface Incident {
  id: string;
  status: string;
  product_name: string;
  reference: string;
  store_name: string;
  affected_quantity: number;
  updated_at: string;
  published_at: string;
  mode: Mode;
  recall_id: string;
  assigned_to?: string | null;
  review_status?: string;
}
export interface Evidence {
  id: string;
  kind: string;
  label: string;
  payload: Record<string, unknown>;
  source_url: string | null;
  created_at: string;
  synthetic: boolean;
}
export interface Decision {
  id: string;
  inventory_lot_id: string;
  recall_version_id: string;
  verdict: string;
  explanation: string;
  action: string;
  evidence_ids: string[];
  created_at: string;
  quantity: number;
  lot: string | null;
  previous_verdict: string | null;
}
export interface Run {
  id: string;
  event_id: string;
  status: string;
  active_node: string;
  llm_mode: string;
  latency_ms: number | null;
  created_at: string;
  steps: Step[];
  summary: string;
  draft: string;
}
export interface Step {
  node: string;
  tool: string;
  input: Record<string, unknown>;
  output: unknown;
  timestamp: string;
  latency_ms: number;
}
export interface Hold {
  id: string;
  inventory_lot_id: string;
  quantity: number;
  status: string;
  created_at: string;
}
export interface History {
  id: string;
  kind: string;
  created_at: string;
  payload: Record<string, unknown>;
}
export interface Detail {
  incident: Incident;
  recall: Recall;
  inventory: Inventory[];
  evidence: Evidence[];
  targets: {
    id: string;
    gtin: string;
    recall_version_id: string;
    scope: Record<string, unknown>;
  }[];
  decisions: Decision[];
  holds: Hold[];
  runs: Run[];
  history: History[];
}
export interface Settings {
  llm_enabled: boolean;
  llm_model: string;
  auth_required: boolean;
  demo_enabled: boolean;
  last_successful_sync: string | null;
  last_sync_error: string | null;
  coverage: string;
  dataset_url: string;
  mode: string;
  source_count: number;
  refresh_interval_seconds: number;
}
export interface Dashboard {
  active_incidents: number;
  affected_units: number;
  awaiting_review: number;
  completed_actions: number;
  inventory_units: number;
  recall_count: number;
  latest_incidents: Incident[];
  activity: History[];
  settings: Settings;
  outcomes: { name: string; value: number }[];
}
export interface Replay {
  id: string;
  step: number;
  incident_id: string;
  events: {
    step: number;
    label: string;
    event_id: string;
    run_id: string | null;
    created_at: string;
  }[];
  detail: Detail;
}
export interface Evaluation {
  id: string;
  created_at: string;
  sample_size: number;
  benchmark: string;
  results: {
    method: string;
    precision: number;
    recall: number;
    f1: number;
    false_hold_rate: number;
    review_accuracy: number;
    latency_ms: number;
    revision_rate: number | null;
    p50_latency_ms?: number;
    p95_latency_ms?: number;
    missed_hold_rate?: number;
    review_request_rate?: number;
  }[];
  cases: Record<string, unknown>[];
}
export function token() {
  return sessionStorage.getItem("recallops-token") || "";
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const r = await fetch(`/api${path}`, { ...options, headers });
  if (!r.ok) {
    const e = await r
      .json()
      .catch(() => ({ error: { message: r.statusText } }));
    const detail = e.error?.message || e.detail;
    const message = Array.isArray(detail)
      ? detail
          .map(
            (item: { loc?: (string | number)[]; msg?: string }) =>
              `${item.loc?.filter((part) => part !== "body").join(" → ") || "Input"}: ${item.msg || "Invalid value"}`,
          )
          .join("; ")
      : typeof detail === "string"
        ? detail
        : "Request failed";
    throw new Error(message);
  }
  return r.json() as Promise<T>;
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export function useApi<T>(path: string) {
  return useQuery<T, Error>({
    queryKey: [path],
    queryFn: () => api<T>(path),
    refetchInterval: 15000,
    retry: 1,
  });
}
export const when = (s: string | null | undefined) =>
  s
    ? new Date(s).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not yet recorded";
