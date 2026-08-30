"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import BatchRunSummary from "@/components/reconciliation/BatchRunSummary";
import DashboardMetrics from "@/components/reconciliation/DashboardMetrics";
import SourceUploadPanel from "@/components/reconciliation/SourceUploadPanel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listRuns } from "@/lib/api/client";
import type { RunListItem } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

export default function DashboardPage() {
  const [latest, setLatest] = useState<RunListItem | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    listRuns()
      .then((runs) => setLatest(runs[0] ?? null))
      .catch(() => setLatest(null));
  }, [refreshKey]);

  return (
    <div className="space-y-6" data-refresh-key={refreshKey}>
      <DashboardMetrics summary={latest?.summary ?? null} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card className="shadow-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">Latest batch</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground">
              {latest ? (
                <div className="space-y-1.5">
                  <p>
                    Run{" "}
                    <Link
                      href={`/runs/${latest.run_id}`}
                      className="font-mono text-primary hover:underline"
                    >
                      {latest.run_id.slice(0, 8)}
                    </Link>{" "}
                    · {formatDateTime(latest.created_at)} · status{" "}
                    <Badge variant="secondary">{latest.status}</Badge>
                  </p>
                  <p>
                    Strategy counts:{" "}
                    {Object.entries(latest.summary.strategy_counts)
                      .map(([strategy, count]) => `${strategy}=${count}`)
                      .join(", ") || "—"}
                  </p>
                </div>
              ) : (
                <p>Start a reconciliation run from the upload panel.</p>
              )}
              {latest && (
                <Link
                  href="/exceptions"
                  className="inline-block pt-1.5 text-primary hover:underline"
                >
                  Review exceptions →
                </Link>
              )}
            </CardContent>
          </Card>

          <BatchRunSummary refreshKey={refreshKey} />
        </div>

        <SourceUploadPanel onImported={refresh} />
      </div>
    </div>
  );
}
