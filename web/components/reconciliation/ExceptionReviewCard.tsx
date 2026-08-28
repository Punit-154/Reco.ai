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
            2a · Deterministic evidence
          </p>
          <p className="mt-0.5 text-[11px]">
            {row.evidence?.explanation ?? "—"}
          </p>
        </section>

        <Separator />

        <section aria-label="rule-trace">
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            2b · Why not auto-matched?
          </p>
          <ol className="mt-1 space-y-1">
            <li className="flex items-start gap-1.5 font-mono text-[10px]">
              <span className="mt-0.5 shrink-0 text-red-500">✗</span>
              <span>
                <span className="font-semibold">Step 1: EXACT_UTR_AMOUNT</span>
                {" — "}
                <span className="text-muted-foreground">
                  {facts.normalizedUtr
                    ? `UTR ${facts.normalizedUtr} matched ${row.evidence?.related_settlement_transaction_ids?.length ?? 0} settlement(s) — not uniquely matchable`
                    : "No UTR on this bank credit"}
                </span>
              </span>
            </li>
            <li className="flex items-start gap-1.5 font-mono text-[10px]">
              <span className="mt-0.5 shrink-0 text-red-500">✗</span>
              <span>
                <span className="font-semibold">Step 2: AMOUNT_DATE_WINDOW</span>
                {" — "}
                <span className="text-muted-foreground">
                  {facts.candidateDeltas && facts.candidateDeltas.length > 0
                    ? `${facts.candidateDeltas.length} amount candidate(s) within ±2 days — ambiguous`
                    : "No unique amount match within ±2 days"}
                </span>
              </span>
            </li>
            <li className="flex items-start gap-1.5 font-mono text-[10px]">
              <span className="mt-0.5 shrink-0 text-red-500">✗</span>
              <span>
                <span className="font-semibold">Step 3: LEDGER_NET_EXACT</span>
                {" — "}
                <span className="text-muted-foreground">
                  {row.evidence?.reason_code === "NO_CANDIDATE"
                    ? "No ledger entry with matching gross/fee/tax equation"
                    : "Ledger equation ambiguous — multiple candidates or missing ledger"}
                </span>
              </span>
            </li>
          </ol>
          {!!facts.candidateDeltas?.length && (
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">
              Delta vs candidates:{" "}
              {facts.candidateDeltas.map((d) =>
                `${d > 0 ? "+" : ""}${(d / 100).toFixed(2)} ₹`
              ).join(", ")}
            </p>
          )}
        </section>

        <Separator />

        <section aria-label="ai-hypothesis">
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            3 · AI hypothesis ({row.model_name?.startsWith("groq") ? "AI" : row.model_name === "fake" ? "Offline" : row.model_name ?? "not classified"})
            <Badge
              variant="outline"
              className="ml-1.5 align-middle text-[9px] text-green-700 border-green-300"
              title="Output strictly validated via Pydantic. Autonomous ledger-posting disabled."
            >
              🛡 guarded
            </Badge>
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

        {!overrideMode && row.status === "unresolved" && (
          <Input
            placeholder="Reason for reject (optional here)"
            className="h-7 text-xs"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}
      </CardContent>

      <CardFooter className="gap-1 pt-0">
        {!overrideMode && row.status === "unresolved" ? (
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
