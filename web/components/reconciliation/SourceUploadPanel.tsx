"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Sparkles, Upload, Zap, Check, Loader2, Download, Database } from "lucide-react";
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
  fetchRazorpayLive,
  generateSampleData,
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

  const [razorpaySettlements, setRazorpaySettlements] = useState<Record<string, unknown>[]>([]);
  const [fetchingLive, setFetchingLive] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    listSources().then(setSources).catch(() => {});
  }, [summaries, pipelineResult, razorpaySettlements]);

  const allFilesSelected = SOURCES.every((s) => files[s.kind]);
  const hasSettlements = razorpaySettlements.length > 0 || sources.some((s) => s.kind === "razorpay_settlements" && s.txn_count > 0);

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

  async function handleFetchRazorpay() {
    setFetchingLive(true);
    try {
      const result = await fetchRazorpayLive();
      setRazorpaySettlements(result.settlements);
      const count = result.count ?? result.settlements?.length ?? 0;
      toast.success(`Fetched ${count} settlements from Razorpay API`);
      onImported?.();
    } catch (e) {
      toast.error(`Razorpay API: ${(e as Error).message}`);
    } finally {
      setFetchingLive(false);
    }
  }

  async function handleGenerateSample() {
    setGenerating(true);
    try {
      const result = await generateSampleData();
      toast.success(
        `Generated ${result.bank_rows} bank rows + ${result.ledger_rows} ledger rows from settlements`
      );
      onImported?.();
    } catch (e) {
      toast.error(`Sample generation: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
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

  const hasData = hasSettlements || SOURCES.some((s) => files[s.kind] || summaries[s.kind]);

  async function handlePipeline() {
    setBusy(true);
    setPipelineResult(null);

    try {
      setPipelineStep("uploading");
      for (const source of SOURCES) {
        const file = files[source.kind];
        if (file && !summaries[source.kind]) {
          const summary = await uploadSource(source.kind, file);
          setSummaries((prev) => ({ ...prev, [source.kind]: summary }));
          onImported?.();
        }
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
    <Card className="shadow-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold">Source uploads</CardTitle>
        <CardDescription className="text-xs">
          Connect to Razorpay API or upload CSV/JSON files to reconcile.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {sources.map((s) => (
              <Badge key={`${s.kind}-${s.name}`} variant="secondary" className="text-[10px] font-mono">
                {s.kind}: {s.txn_count} txns
              </Badge>
            ))}
          </div>
        )}

        <div className="rounded-md border border-primary/20 bg-primary/5 p-3 space-y-2">
          <p className="text-xs font-semibold text-primary">Live Razorpay Connection</p>
          <p className="text-[11px] text-muted-foreground">
            Fetch settlements directly from Razorpay&apos;s Settlements API using your test-mode keys.
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              className="h-8"
              disabled={fetchingLive}
              onClick={handleFetchRazorpay}
            >
              {fetchingLive ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Download className="size-3" />
              )}{" "}
              Fetch from Razorpay
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8"
              disabled={generating || !hasSettlements}
              onClick={handleGenerateSample}
            >
              {generating ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Database className="size-3" />
              )}{" "}
              Generate sample bank + ledger
            </Button>
          </div>
          {razorpaySettlements.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase">
                Fetched {razorpaySettlements.length} settlements
              </p>
              <div className="max-h-24 space-y-0.5 overflow-y-auto">
                {razorpaySettlements.slice(0, 10).map((s, i) => (
                  <div key={i} className="flex items-center justify-between font-mono text-[10px] text-muted-foreground">
                    <span>{String(s.id ?? "").slice(0, 20)}</span>
                    <span>₹{((Number(s.amount ?? 0)) / 100).toLocaleString("en-IN")}</span>
                    <span>{String(s.utr ?? "—")}</span>
                  </div>
                ))}
                {razorpaySettlements.length > 10 && (
                  <p className="text-[9px] text-muted-foreground">
                    ...and {razorpaySettlements.length - 10} more
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        <Separator />

        {SOURCES.map((source) => (
          <div key={source.kind} className="space-y-1.5">
            <Label className="text-xs font-medium">{source.label}</Label>
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
            disabled={busy || !hasData}
            onClick={handlePipeline}
          >
            {busy && pipelineStep ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Zap className="size-3" />
            )}{" "}
            Run pipeline
          </Button>
          <Button size="sm" className="h-8" disabled={busy || !hasData} onClick={handleRun}>
            <Play className="size-3" /> Reconcile
          </Button>
          <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={handleClassify}>
            <Sparkles className="size-3" /> Classify
          </Button>
        </div>

        {pipelineStep && pipelineStep !== "done" && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {STEP_LABELS[pipelineStep]}...
          </div>
        )}

        {pipelineResult && (
          <div className="rounded-md border p-3 space-y-2 text-xs bg-muted/30">
            <div className="flex items-center gap-1.5 font-medium">
              <Check className="size-3 text-success" /> Pipeline complete
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px]">
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
