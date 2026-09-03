import type {
  AuditEvent,
  DecisionResult,
  ExceptionRow,
  IngestionSummary,
  MatchGroupRow,
  RunListItem,
  RunMetricsResponse,
  ReconciliationRunResponse,
  SourceStatus,
} from "./types";

const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export async function uploadSource(
  kind: "bank" | "ledger" | "razorpay-settlements",
  file: File
): Promise<IngestionSummary> {
  const form = new FormData();
  form.append("file", file);
  return request<IngestionSummary>(`/api/imports/${kind}`, {
    method: "POST",
    body: form,
  });
}

export async function startReconciliationRun(): Promise<ReconciliationRunResponse> {
  return request<ReconciliationRunResponse>("/api/reconciliation-runs", {
    method: "POST",
  });
}

export async function listRuns(): Promise<RunListItem[]> {
  return request<RunListItem[]>("/api/reconciliation-runs");
}

export async function getRun(runId: string): Promise<ReconciliationRunResponse> {
  return request<ReconciliationRunResponse>(`/api/reconciliation-runs/${runId}`);
}

export async function getRunMatches(runId: string): Promise<MatchGroupRow[]> {
  return request<MatchGroupRow[]>(`/api/reconciliation-runs/${runId}/matches`);
}

export async function getRunMetrics(runId: string): Promise<RunMetricsResponse> {
  return request<RunMetricsResponse>(`/api/reconciliation-runs/${runId}/metrics`);
}

export async function classifyPending(
  useAi = false
): Promise<{ classifier: string; classified: number; deferred_retry: number; by_category: Record<string, number> }> {
  return request("/api/exceptions/classify-pending", {
    method: "POST",
    body: JSON.stringify({ use_ai: useAi, limit: 200 }),
  });
}

export async function listExceptions(): Promise<ExceptionRow[]> {
  return request<ExceptionRow[]>("/api/exceptions");
}

export async function clearAllExceptions(): Promise<{ cleared: boolean; tables_truncated: number }> {
  return request("/api/exceptions", { method: "DELETE" });
}

export async function getException(id: string): Promise<ExceptionRow> {
  return request<ExceptionRow>(`/api/exceptions/${id}`);
}

export async function decideException(
  id: string,
  payload: { action: "approve" | "reject" | "manual_override"; reason?: string; override_category?: string }
): Promise<DecisionResult> {
  return request<DecisionResult>(`/api/exceptions/${id}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listAuditLogs(params?: {
  entity_type?: string;
  entity_id?: string;
}): Promise<AuditEvent[]> {
  const search = new URLSearchParams();
  if (params?.entity_type) search.set("entity_type", params.entity_type);
  if (params?.entity_id) search.set("entity_id", params.entity_id);
  const qs = search.toString();
  return request<AuditEvent[]>(`/api/exceptions/audit-logs${qs ? `?${qs}` : ""}`);
}

export async function listSources(): Promise<SourceStatus[]> {
  return request<SourceStatus[]>("/api/imports/sources");
}

export async function fetchRazorpayLive(): Promise<{
  ingestion: IngestionSummary;
  settlements: Record<string, unknown>[];
  count: number;
}> {
  return request("/api/imports/razorpay-live", { method: "POST" });
}

export async function generateSampleData(): Promise<{
  bank: IngestionSummary;
  ledger: IngestionSummary;
  bank_rows: number;
  ledger_rows: number;
}> {
  return request("/api/imports/generate-sample", { method: "POST" });
}
