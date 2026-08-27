"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Sparkles, Upload, Zap, Check, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  classifyPending,
  getRunMetrics,
  listSources,
  startReconciliationRun,
  uploadSource,
} from "@/lib/api/client";
import type { IngestionSummary, SourceStatus } from "@/lib/api/types";

const SOURCES: { kind: "bank" | "ledger" | "razorpay-settlements"; label: string; accept: string }[] = [
  { kind: "bank", label: "Bank statement (CSV)", accept: ".csv" },
  { kind: "ledger", label: "Ledger (CSV)", accept: ".csv" },
  { kind: "razorpay-settlements", label: "Razorpay settlements (JSON)", accept: ".json" },
];

type PipelineStep = "uploading" | "reconciling" | "classifying" | "done";

const STEP_LABELS: Record<PipelineStep, string> = {
  uploading: "Uploading sources",
  reconciling: "Running reconciliation",
  classifying: "Classifying exceptions",
  done: "Pipeline complete",
};

export default function SourceUploadPanel({ onImported }: { onImported?: () => void }) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [summaries, setSummaries] = useState<Record<string, IngestionSummary>>({});
  const [busy, setBusy] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [pipelineStep, setPipelineStep] = useState<PipelineStep | null>(null);
  const [pipelineResult, setPipelineResult] = useState<{
    runId: string;
    matched: number;
    exceptions: number;
    classified: number;
    classifier: string;
    byCategory: Record<string, number>;
  } | null>(null);

  useEffect(() => {
    listSources().then(setSources).catch(() => {});
  }, [summaries, pipelineResult]);

  const allFilesSelected = SOURCES.every((s) => files[s.kind]);

  async function handleUpload(kind: string) {
    const file = files[kind];
    if (!file) return;
    setBusy(true);
    try {
      const summary = await uploadSource(kind as "bank" | "ledger" | "razorpay-settlements", file);
      setSummaries((prev) => ({ ...prev, [kind]: summary }));
      toast.success(
        `${kind}: inserted ${summary.inserted}, skipped ${summary.skipped_duplicates}, failed ${summary.failed_rows}`
      );
      onImported?.();
    } catch (e) {
      toast.error(`Upload failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleRun() {
    setBusy(true);
    try {
      const run = await startReconciliationRun();
      toast.success(
        `Run ${run.run_id.slice(0, 8)}: ${run.summary.matched_bank_transactions} matched, ${run.summary.exceptions_created} exceptions`
      );
      onImported?.();
    } catch (e) {
      toast.error(`Run failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleClassify() {
    setBusy(true);
    try {
      const result = await classifyPending(useAi);
      toast.success(
        `Classified ${result.classified} residue exceptions (${result.classifier})`
      );
      onImported?.();
    } catch (e) {
      toast.error(`Classification failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handlePipeline() {
    if (!allFilesSelected) return;
    setBusy(true);
    setPipelineResult(null);

    try {
      setPipelineStep("uploading");
      for (const source of SOURCES) {
        const file = files[source.kind]!;
        const summary = await uploadSource(source.kind, file);
        setSummaries((prev) => ({ ...prev, [source.kind]: summary }));
      }

      setPipelineStep("reconciling");
      const run = await startReconciliationRun();

      setPipelineStep("classifying");
      const cls = await classifyPending(useAi);

      setPipelineStep("done");
      setPipelineResult({
        runId: run.run_id,
        matched: run.summary.matched_bank_transactions,
        exceptions: run.summary.exceptions_created,
        classified: cls.classified,
        classifier: cls.classifier,
        byCategory: cls.by_category,
      });

      toast.success(`Pipeline complete: ${run.summary.matched_bank_transactions} matched, ${cls.classified} classified`);
      onImported?.();
    } catch (e) {
      toast.error(`Pipeline failed: ${(e as Error).message}`);
      setPipelineStep(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Source uploads</CardTitle>
        <CardDescription className="text-xs">
          Upload CSV/JSON files to reconcile. Files are normalized to integer paise.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {sources.map((s) => (
              <Badge key={`${s.kind}-${s.name}`} variant="secondary" className="text-[10px] font-mono">
                {s.kind}: {s.txn_count} txns
              </Badge>
            ))}
          </div>
        )}

        {SOURCES.map((source) => (
          <div key={source.kind} className="space-y-1">
            <Label className="text-xs">{source.label}</Label>
            <div className="flex items-center gap-2">
              <Input
                ref={(el) => {
                  inputRefs.current[source.kind] = el;
                }}
                type="file"
                accept={source.accept}
                className="h-8 text-xs"
                onChange={(e) =>
                  setFiles((prev) => ({ ...prev, [source.kind]: e.target.files?.[0] ?? null }))
                }
              />
              <Button
                size="sm"
                variant="secondary"
                className="h-8"
                disabled={busy || !files[source.kind]}
                onClick={() => handleUpload(source.kind)}
              >
                <Upload className="size-3" /> Upload
              </Button>
            </div>
            {summaries[source.kind] && (
              <p className="font-mono text-[11px] text-muted-foreground">
                inserted {summaries[source.kind].inserted} · skipped{" "}
                {summaries[source.kind].skipped_duplicates} · failed{" "}
                {summaries[source.kind].failed_rows}
              </p>
            )}
          </div>
        ))}

        <Separator />

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
              className="accent-primary"
            />
            Use AI
          </label>
          <span className="text-[10px] text-muted-foreground">
            {useAi ? "Groq (live)" : "Fake classifier (offline)"}
          </span>
        </div>

        <div className="flex gap-2">
          <Button
            size="sm"
            className="h-8"
            disabled={busy || !allFilesSelected}
            onClick={handlePipeline}
          >
            {busy && pipelineStep ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Zap className="size-3" />
            )}{" "}
            Run full pipeline
          </Button>
          <Button size="sm" className="h-8" disabled={busy} onClick={handleRun}>
            <Play className="size-3" /> Run reconciliation
          </Button>
          <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={handleClassify}>
            <Sparkles className="size-3" /> Classify pending
          </Button>
        </div>

        {pipelineStep && pipelineStep !== "done" && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {STEP_LABELS[pipelineStep]}...
          </div>
        )}

        {pipelineResult && (
          <div className="rounded-md border p-2.5 space-y-1.5 text-xs bg-muted/30">
            <div className="flex items-center gap-1.5 font-medium">
              <Check className="size-3 text-green-600" /> Pipeline complete
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[11px]">
              <span className="text-muted-foreground">matched</span>
              <span>{pipelineResult.matched}</span>
              <span className="text-muted-foreground">exceptions</span>
              <span>{pipelineResult.exceptions}</span>
              <span className="text-muted-foreground">classified</span>
              <span>{pipelineResult.classified} ({pipelineResult.classifier})</span>
            </div>
            {Object.keys(pipelineResult.byCategory).length > 0 && (
              <div className="flex flex-wrap gap-1 pt-0.5">
                {Object.entries(pipelineResult.byCategory).map(([cat, count]) => (
                  <Badge key={cat} variant="outline" className="text-[9px] font-mono">
                    {cat}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
