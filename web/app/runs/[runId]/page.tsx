"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";

import DashboardMetrics from "@/components/reconciliation/DashboardMetrics";
import EvaluationPanel from "@/components/reconciliation/EvaluationPanel";
import MatchTable from "@/components/reconciliation/MatchTable";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import {
  getRun,
  getRunMetrics,
  listExceptions,
} from "@/lib/api/client";
import type { ExceptionRow, RunMetricsResponse } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = use(params);
  const [run, setRun] = useState<Awaited<ReturnType<typeof getRun>> | null>(null);
  const [metrics, setMetrics] = useState<RunMetricsResponse | null>(null);
  const [exceptionCounts, setExceptionCounts] = useState<{
    unresolved: number;
    decided: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRun(runId)
      .then(setRun)
      .catch((e) => setError(String(e.message ?? e)));
    getRunMetrics(runId)
      .then(setMetrics)
      .catch(() => setMetrics(null));
    listExceptions()
      .then((rows: ExceptionRow[]) =>
        setExceptionCounts({
          unresolved: rows.filter((r) => r.status === "unresolved").length,
          decided: rows.filter((r) => r.status !== "unresolved").length,
        })
      )
      .catch(() => setExceptionCounts(null));
  }, [runId]);

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-red-600">{error}</CardTitle>
        </CardHeader>
        <CardContent>
          <Link href="/" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to dashboard
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold">
            Run <span className="font-mono">{runId.slice(0, 8)}</span>{" "}
            <Badge variant="secondary">{run?.status ?? "…"}</Badge>
          </h1>
          <p className="text-xs text-muted-foreground">
            Created {formatDateTime(run ? null : null) || "—"}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/exceptions"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Exception review flow →
          </Link>
        </div>
      </div>

      <DashboardMetrics summary={run?.summary ?? null} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <MatchTable runId={runId} />
        </div>
        <div className="space-y-4">
          <EvaluationPanel runId={runId} />
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Residue</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-xs text-muted-foreground">
              <p>
                Unresolved exceptions:{" "}
                <span className="font-mono">{exceptionCounts?.unresolved ?? "—"}</span>
              </p>
              <p>
                Decided by reviewer:{" "}
                <span className="font-mono">{exceptionCounts?.decided ?? "—"}</span>
              </p>
              <Link href="/exceptions" className="inline-block text-blue-700 hover:underline">
                Open review flow →
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>

      {metrics?.evaluation && (
        <p className="text-[11px] text-muted-foreground">
          Evaluation run <span className="font-mono">{metrics.evaluation.evaluation_run_id.slice(0, 8)}</span> attached to this reconciliation run.
        </p>
      )}
    </div>
  );
}
