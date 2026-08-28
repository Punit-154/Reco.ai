export interface IngestionSummary {
  ingestion_run_id: string;
  source_id: string;
  source_kind: string;
  inserted: number;
  skipped_duplicates: number;
  failed_rows: number;
  errors: { row_number: number; error: string }[];
}

export interface RunSummaryData {
  total_bank_transactions: number;
  matched_bank_transactions: number;
  unmatched_bank_transactions: number;
  deterministic_match_rate: number;
  exceptions_created: number;
  strategy_counts: Record<string, number>;
  match_groups_created: number;
  match_groups_total: number;
  exceptions_total: number;
  exceptions_by_category: Record<string, number>;
}

export interface ReconciliationRunResponse {
  run_id: string;
  status: string;
  summary: RunSummaryData;
}

export interface RunListItem extends ReconciliationRunResponse {
  created_at: string;
}

export interface MatchMemberRow {
  role: string;
  transaction_id: string;
  external_id: string;
  amount_paise: number;
  allocated_paise: number;
  effective_date: string;
  utr: string | null;
}

export interface MatchGroupRow {
  group_id: string;
  strategy: string;
  status: string;
  deterministic_score: number | null;
  expected_amount_paise: number | null;
  actual_amount_paise: number | null;
  delta_paise: number | null;
  members: MatchMemberRow[];
  rule_trace: Record<string, unknown> | null;
}

export interface AiHypothesis {
  category: string;
  confidence: number;
  explanation: string;
  evidence_transaction_ids: string[];
  requires_human_review: boolean;
}

export interface ExceptionEvidence {
  reason_code?: string;
  explanation?: string;
  normalized_utr?: string | null;
  bank_transaction_id?: string;
  bank_external_id?: string;
  bank_amount_paise?: number;
  bank_currency?: string;
  bank_effective_date?: string;
  candidate_deltas_paise?: number[];
  related_settlement_transaction_ids?: string[];
}

export interface ExceptionRow {
  id: string;
  status: "unresolved" | "approved" | "rejected" | "overridden";
  taxonomy: string | null;
  confidence: number | null;
  model_name: string | null;
  prompt_version: string | null;
  response: AiHypothesis | null;
  evidence: ExceptionEvidence | null;
  faithfulness_score: number | null;
  retry_count: number;
}

export interface AuditEvent {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  previous_state: Record<string, unknown> | null;
  new_state: Record<string, unknown> | null;
  ai_hypothesis: Record<string, unknown> | null;
  reason: string | null;
  created_at: string;
}

export interface DecisionResult {
  exception: ExceptionRow;
  audit_event: AuditEvent;
}

export interface EvaluationMetrics {
  reconciliation_run_id: string | null;
  fixture_version: string;
  seed: number | null;
  total_cases: number;
  deterministic_match_rate: number;
  deterministic_coverage: number;
  exception_recall: number;
  ai_classification_accuracy: number;
  llm_faithfulness_score: number;
  counts: Record<string, number>;
}

export interface RunMetricsResponse {
  reconciliation_run_id: string;
  status: string;
  summary: RunSummaryData;
  evaluation: { evaluation_run_id: string; metrics: EvaluationMetrics } | null;
}

export interface SourceStatus {
  kind: string;
  name: string;
  txn_count: number;
}
