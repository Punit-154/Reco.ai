"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { listRuns } from "@/lib/api/client";
import type { RunListItem } from "@/lib/api/types";
import { formatDateTime, formatPct } from "@/lib/format";

export default function BatchRunSummary({ refreshKey = 0 }: { refreshKey?: number }) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((e) => setError(String(e.message ?? e)));
  }, [refreshKey]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Reconciliation runs</CardTitle>
        <CardDescription className="text-xs">
          Latest deterministic batches (newest first)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
        {runs.length === 0 && !error && (
          <p className="text-xs text-muted-foreground">
            No runs yet — upload sources and start a run.
          </p>
        )}
        {runs.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-8 text-xs">Run</TableHead>
                <TableHead className="h-8 text-xs">Created</TableHead>
                <TableHead className="h-8 text-xs">Matched</TableHead>
                <TableHead className="h-8 text-xs">Unmatched</TableHead>
                <TableHead className="h-8 text-xs">Rate</TableHead>
                <TableHead className="h-8 text-xs">Exceptions</TableHead>
                <TableHead className="h-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.run_id}>
                  <TableCell className="py-1.5 font-mono text-xs">
                    {run.run_id.slice(0, 8)}
                  </TableCell>
                  <TableCell className="py-1.5 text-xs">
                    {formatDateTime(run.created_at)}
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    {run.summary.matched_bank_transactions}
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    {run.summary.unmatched_bank_transactions}
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    <Badge variant="secondary">
                      {formatPct(run.summary.deterministic_match_rate)}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    {run.summary.exceptions_total}
                  </TableCell>
                  <TableCell className="py-1.5 text-right">
                    <Link
                      href={`/runs/${run.run_id}`}
                      className="inline-flex items-center gap-1 text-xs text-blue-700 hover:underline"
                    >
                      details <ArrowRight className="size-3" />
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
