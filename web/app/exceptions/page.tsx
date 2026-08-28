"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

import AuditTimeline from "@/components/reconciliation/AuditTimeline";
import ExceptionReviewCard from "@/components/reconciliation/ExceptionReviewCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { classifyPending, listExceptions, listRuns, getRunMetrics } from "@/lib/api/client";
import type { ExceptionRow, EvaluationMetrics } from "@/lib/api/types";
import { formatPct } from "@/lib/format";

const STATUS_FILTERS = ["all", "unresolved", "approved", "rejected", "overridden"] as const;

export default function ExceptionsPage() {
  const [rows, setRows] = useState<ExceptionRow[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("unresolved");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalMetrics, setEvalMetrics] = useState<EvaluationMetrics | null>(null);
  const [prevCount, setPrevCount] = useState<number | null>(null);
  const [newAlert, setNewAlert] = useState<string | null>(null);
  const [auditVersion, setAuditVersion] = useState(0);

  const refresh = useCallback(() => {
    listExceptions()
      .then(setRows)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    listRuns()
      .then((runs) => runs[0] ? getRunMetrics(runs[0].run_id) : null)
      .then((res) => { if (res?.evaluation?.metrics) setEvalMetrics(res.evaluation.metrics); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (prevCount === null) { setPrevCount(rows.length); return; }
    if (rows.length > prevCount) {
      const added = rows.length - prevCount;
      const newUnresolved = rows.filter((r) => r.status === "unresolved").length;
      const msg = `⚠️ ${added} new exception${added > 1 ? "s" : ""} detected — ${newUnresolved} unresolved`;
      setNewAlert(msg);
      toast.warning(msg, { duration: 6000 });
    }
    setPrevCount(rows.length);
  }, [rows]);

  const filtered = useMemo(
    () =>
      statusFilter === "all"
        ? rows
        : rows.filter((row) => row.status === statusFilter),
    [rows, statusFilter]
  );

  const selected =
    filtered.find((row) => row.id === selectedId) ?? filtered[0] ?? null;

  async function handleClassify() {
    setBusy(true);
    try {
      const result = await classifyPending(true);
      toast.success(`Classified ${result.classified} exceptions (${result.classifier})`);
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function handleDecided() {
    refresh();
    setAuditVersion((v) => v + 1);
  }

  return (
    <div className="space-y-4">
      {newAlert && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
        >
          <span className="font-medium">{newAlert}</span>
          <button
            className="ml-4 text-amber-600 hover:text-amber-900 font-bold"
            onClick={() => setNewAlert(null)}
            aria-label="Dismiss alert"
          >
            ✕
          </button>
        </div>
      )}

      {evalMetrics && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/60 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="text-sm font-semibold text-blue-900">
              📊 Evaluation vs Ground Truth
            </span>
            <span className="font-mono text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
              {evalMetrics.total_cases} cases · seed {String(evalMetrics.seed ?? "fixed")}
            </span>
            <span className="ml-auto text-[10px] italic text-blue-500">
              Ground truth isolated from matcher and prompts
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-5">
            {[
              { label: "Det. Match Score", value: evalMetrics.deterministic_match_rate },
              { label: "Det. Coverage", value: evalMetrics.deterministic_coverage },
              { label: "Exception Recall", value: evalMetrics.exception_recall },
              { label: "AI Accuracy", value: evalMetrics.ai_classification_accuracy },
              { label: "LLM Faithfulness", value: evalMetrics.llm_faithfulness_score },
            ].map((m) => (
              <div key={m.label} className="flex flex-col">
                <span className="text-[10px] font-medium uppercase tracking-wide text-blue-700">
                  {m.label}
                </span>
                <span className="font-mono text-xl font-bold text-blue-900 tabular-nums leading-tight">
                  {formatPct(m.value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold">Exception review flow</h1>
        <div className="flex items-center gap-2">
          <Select
            value={statusFilter}
            onValueChange={(value) => setStatusFilter(value ?? "unresolved")}
          >
            <SelectTrigger className="h-8 w-[150px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((status) => (
                <SelectItem key={status} value={status} className="text-xs">
                  {status}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs"
            disabled={busy}
            onClick={handleClassify}
          >
            <RefreshCw className="size-3" /> Classify pending
          </Button>
        </div>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {filtered.length === 0 && !error && (
        <p className="text-xs text-muted-foreground">
          No exceptions for this filter. Run a reconciliation and classification first.
        </p>
      )}

      {filtered.length > 0 && selected && (
        <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
          <aside className="max-h-[75vh] space-y-2 overflow-y-auto pr-1">
            {filtered.map((row) => (
              <button
                key={row.id}
                onClick={() => setSelectedId(row.id)}
                className={`w-full rounded border px-2 py-1.5 text-left transition-colors ${
                  row.id === selected.id ? "border-blue-600 bg-blue-50" : "hover:bg-muted"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px]">{row.id.slice(0, 8)}</span>
                  <Badge
                    variant={row.status === "unresolved" ? "destructive" : "secondary"}
                    className="text-[10px]"
                  >
                    {row.status}
                  </Badge>
                </div>
                <span className="text-[11px] text-muted-foreground">
                  {row.response?.category ?? row.taxonomy ?? "—"}
                </span>
              </button>
            ))}
          </aside>

          <div className="grid gap-4 md:grid-cols-2">
            <ExceptionReviewCard row={selected} onDecided={handleDecided} />
            <AuditTimeline statusFilter={statusFilter} version={auditVersion} />
          </div>
        </div>
      )}
    </div>
  );
}
