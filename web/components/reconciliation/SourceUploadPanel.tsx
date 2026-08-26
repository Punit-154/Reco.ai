"use client";

import { useRef, useState } from "react";
import { Play, Sparkles, Upload } from "lucide-react";
import { toast } from "sonner";

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
  startReconciliationRun,
  uploadSource,
} from "@/lib/api/client";
import type { IngestionSummary } from "@/lib/api/types";

const SOURCES: { kind: "bank" | "ledger" | "razorpay-settlements"; label: string; accept: string }[] = [
  { kind: "bank", label: "Bank statement (CSV)", accept: ".csv" },
  { kind: "ledger", label: "Ledger (CSV)", accept: ".csv" },
  { kind: "razorpay-settlements", label: "Razorpay settlements (JSON)", accept: ".json" },
];

export default function SourceUploadPanel({ onImported }: { onImported?: () => void }) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [summaries, setSummaries] = useState<Record<string, IngestionSummary>>({});
  const [busy, setBusy] = useState(false);
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

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
        `Run ${run.run_id.slice(0, 8)}: ${run.summary.matched_bank_transactions} matched, ${run.summary.exceptions_created} exceptions created`
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
      const result = await classifyPending(false);
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

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Source uploads</CardTitle>
        <CardDescription className="text-xs">
          Synthetic fixtures only. Files are normalized to integer paise.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
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

        <div className="flex gap-2">
          <Button size="sm" className="h-8" disabled={busy} onClick={handleRun}>
            <Play className="size-3" /> Run reconciliation
          </Button>
          <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={handleClassify}>
            <Sparkles className="size-3" /> Classify pending (offline demo)
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
