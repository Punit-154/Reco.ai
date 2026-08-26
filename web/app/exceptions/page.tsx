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
import { classifyPending, listExceptions } from "@/lib/api/client";
import type { ExceptionRow } from "@/lib/api/types";

const STATUS_FILTERS = ["all", "unresolved", "approved", "rejected", "overridden"] as const;

export default function ExceptionsPage() {
  const [rows, setRows] = useState<ExceptionRow[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("unresolved");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listExceptions()
      .then(setRows)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(refresh, [refresh]);

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
      const result = await classifyPending(false);
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
  }

  return (
    <div className="space-y-4">
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
            <AuditTimeline exceptionId={selected.id} />
          </div>
        </div>
      )}
    </div>
  );
}
