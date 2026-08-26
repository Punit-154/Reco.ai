"use client";

import { useEffect, useState } from "react";
import { ClipboardCheck } from "lucide-react";

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
import { getRunMetrics } from "@/lib/api/client";
import type { RunMetricsResponse } from "@/lib/api/types";
import { formatPct } from "@/lib/format";

const METRIC_LABELS: { key: keyof Omit<import("@/lib/api/types").EvaluationMetrics, "counts" | "reconciliation_run_id" | "fixture_version" | "seed" | "total_cases">; label: string; description: string }[] = [
  {
    key: "deterministic_match_rate",
    label: "Deterministic match score",
    description: "correct auto-matches / auto-matches",
  },
  {
    key: "deterministic_coverage",
    label: "Deterministic coverage",
    description: "auto-matches / eligible matchable cases",
  },
  {
    key: "exception_recall",
    label: "Exception recall",
    description: "surfaced known exceptions / known exceptions",
  },
  {
    key: "ai_classification_accuracy",
    label: "AI classification accuracy",
    description: "correct AI classifications / AI-classified cases",
  },
  {
    key: "llm_faithfulness_score",
    label: "LLM faithfulness score",
    description: "mean evidence-support across evaluated explanations",
  },
];

export default function EvaluationPanel({ runId }: { runId: string }) {
  const [metrics, setMetrics] = useState<RunMetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRunMetrics(runId)
      .then(setMetrics)
      .catch((e) => setError(String(e.message ?? e)));
  }, [runId]);

  const evaluation = metrics?.evaluation?.metrics;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1 text-sm">
          <ClipboardCheck className="size-3.5" /> Evaluation
        </CardTitle>
        <CardDescription className="text-xs">
          Reported separately against isolated ground truth (never combined into a
          weighted score)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className="text-xs text-red-600">{error}</p>}
        {!evaluation && !error && (
          <p className="text-xs text-muted-foreground">
            No evaluation stored for this run yet.
          </p>
        )}
        {evaluation && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8 text-xs">Metric</TableHead>
                  <TableHead className="h-8 text-xs">Definition</TableHead>
                  <TableHead className="h-8 text-right text-xs">Value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {METRIC_LABELS.map((metric) => (
                  <TableRow key={metric.key}>
                    <TableCell className="py-1.5 text-xs font-medium">
                      {metric.label}
                    </TableCell>
                    <TableCell className="py-1.5 text-[11px] text-muted-foreground">
                      {metric.description}
                    </TableCell>
                    <TableCell className="py-1.5 text-right font-mono text-xs tabular-nums">
                      {formatPct(evaluation[metric.key])}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Fixture {evaluation.fixture_version} · seed {String(evaluation.seed)} ·{" "}
              {evaluation.total_cases} cases
              {evaluation.counts.ai_classified > 0 &&
                ` · ${evaluation.counts.ai_classified} AI-classified`}
            </p>
            <Badge variant="secondary" className="mt-2 text-[10px]">
              Ground truth isolated from matcher and prompts
            </Badge>
          </>
        )}
      </CardContent>
    </Card>
  );
}
