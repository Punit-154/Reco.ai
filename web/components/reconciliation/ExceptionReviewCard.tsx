"use client";

import { useState } from "react";
import { Check, PencilLine, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { decideException } from "@/lib/api/client";
import type { ExceptionRow } from "@/lib/api/types";
import { formatPaise } from "@/lib/format";

const CATEGORY_OPTIONS = [
  "FEE_DELTA",
  "REFUND_LAG",
  "FX_ROUNDING",
  "DUPLICATE_UTR",
  "UNRECOGNIZED_CREDIT",
  "AMBIGUOUS_MATCH",
];

interface SourceFacts {
  bankExternalId?: string;
  amountPaise?: number | null;
  currency?: string;
  effectiveDate?: string;
  normalizedUtr?: string | null;
  candidateDeltas?: number[];
}

function factsFrom(row: ExceptionRow): SourceFacts {
  const evidence = row.evidence ?? {};
  return {
    bankExternalId:
      evidence.bank_external_id ??
      evidence.bank_transaction_id,
    amountPaise: evidence.bank_amount_paise ?? null,
    currency: evidence.bank_currency,
    effectiveDate: evidence.bank_effective_date,
    normalizedUtr: evidence.normalized_utr ?? null,
    candidateDeltas: evidence.candidate_deltas_paise ?? [],
  };
}

export default function ExceptionReviewCard({
  row,
  onDecided,
}: {
  row: ExceptionRow;
  onDecided?: (updated: ExceptionRow) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [overrideMode, setOverrideMode] = useState(false);
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState<string>("");
  const facts = factsFrom(row);

  async function decide(
    action: "approve" | "reject" | "manual_override",
    needsReason: boolean
  ) {
    if (needsReason && !reason.trim()) {
      toast.error("A reason is required for reject / manual override");
      return;
    }
    if (action === "manual_override" && overrideMode && !category) {
      toast.error("Choose an override category");
      return;
    }
    setBusy(true);
    try {
      const result = await decideException(row.id, {
        action,
        reason: reason.trim() || undefined,
        override_category:
          action === "manual_override" && category ? category : undefined,
      });
      toast.success(`Exception ${result.exception.status}`);
      setOverrideMode(false);
      setReason("");
      setCategory("");
      onDecided?.(result.exception);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const ai = row.response;

  return (
    <Card className="gap-3">
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="font-mono text-xs">{row.id.slice(0, 8)}</CardTitle>
          <div className="flex items-center gap-1">
            <Badge
              variant={
                row.status === "unresolved"
                  ? "destructive"
                  : row.status === "approved"
                    ? "default"
                    : "secondary"
              }
              className="text-[10px]"
            >
              {row.status}
            </Badge>
            <Badge variant="outline" className="text-[10px]">
              {row.taxonomy ?? "—"}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-2 pb-2">
        <section aria-label="source-facts">
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            1 · Source facts
          </p>
          <div className="mt-0.5 grid grid-cols-3 gap-1 font-mono text-[11px]">
            <span className="truncate" title={facts.bankExternalId}>
              bank:{facts.bankExternalId?.slice(0, 18) ?? "—"}
            </span>
            <span>
              {formatPaise(facts.amountPaise)}
              {facts.currency ? ` ${facts.currency}` : ""}
            </span>
            <span>
              {facts.effectiveDate ?? "—"} · UTR:{facts.normalizedUtr ?? "—"}
            </span>
          </div>
          {!!facts.candidateDeltas?.length && (
            <p className="font-mono text-[10px] text-muted-foreground">
              candidate deltas: {facts.candidateDeltas.map(formatPaise).join(", ")}
            </p>
          )}
        </section>

        <Separator />

        <section aria-label="deterministic-evidence">
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            2 · Deterministic evidence
          </p>
          <p className="mt-0.5 text-[11px]">
            {row.evidence?.explanation ?? "—"}
          </p>
        </section>

        <Separator />

        <section aria-label="ai-hypothesis">
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            3 · AI hypothesis ({row.model_name ?? "not classified"})
          </p>
          {ai ? (
            <div className="mt-0.5 space-y-1">
              <div className="flex items-center gap-2">
                <Badge className="text-[10px]">{ai.category}</Badge>
                <span className="font-mono text-[11px] tabular-nums">
                  confidence {(ai.confidence / 100).toFixed(2)}
                </span>
                {row.faithfulness_score !== null && (
                  <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                    faithfulness {row.faithfulness_score.toFixed(2)}
                  </span>
                )}
              </div>
              <p className="text-[11px] leading-snug">{ai.explanation}</p>
              <p className="font-mono text-[10px] break-all text-muted-foreground">
                evidence: {ai.evidence_transaction_ids.join(", ") || "—"}
              </p>
            </div>
          ) : (
            <p className="mt-0.5 text-[11px] text-muted-foreground">Not classified.</p>
          )}
        </section>

        {overrideMode && (
          <section aria-label="override-inputs" className="space-y-2 rounded bg-muted p-2">
            <Select
              value={category}
              onValueChange={(value) => setCategory(value ?? "")}
            >
              <SelectTrigger className="h-7 w-full text-xs">
                <SelectValue placeholder="Override category" />
              </SelectTrigger>
              <SelectContent>
                {CATEGORY_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option} className="text-xs">
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Textarea
              placeholder="Reason (required)"
              className="min-h-[56px] text-xs"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button
              size="sm"
              variant="default"
              className="h-7 text-xs"
              disabled={busy}
              onClick={() => decide("manual_override", true)}
            >
              <PencilLine className="size-3" /> Submit override
            </Button>
          </section>
        )}

        {!overrideMode && (
          <Input
            placeholder="Reason for reject (optional here)"
            className="h-7 text-xs"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}
      </CardContent>

      <CardFooter className="gap-1 pt-0">
        {!overrideMode ? (
          <>
            <Button
              size="sm"
              variant="default"
              className="h-7 text-xs"
              disabled={busy}
              onClick={() => decide("approve", false)}
            >
              <Check className="size-3" /> Approve
            </Button>
            <Button
              size="sm"
              variant="destructive"
              className="h-7 text-xs"
              disabled={busy}
              onClick={() => decide("reject", true)}
            >
              <X className="size-3" /> Reject
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={busy}
              onClick={() => setOverrideMode(true)}
            >
              <PencilLine className="size-3" /> Manual override
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs"
            onClick={() => setOverrideMode(false)}
          >
            Cancel override
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
