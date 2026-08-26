"use client";

import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { ExceptionEvidence } from "@/lib/api/types";

export default function EvidenceDrawer({
  evidence,
  exceptionId,
}: {
  evidence: ExceptionEvidence | null;
  exceptionId: string;
}) {
  return (
    <Sheet>
      <SheetTrigger
        render={
          <Button size="sm" variant="ghost" className="h-7 text-xs">
            <ExternalLink className="size-3" /> Evidence
          </Button>
        }
      />
      <SheetContent side="right" className="w-[420px] overflow-y-auto sm:w-[480px]">
        <SheetHeader>
          <SheetTitle className="text-sm">Deterministic evidence</SheetTitle>
          <SheetDescription className="text-xs">
            Facts computed by the deterministic matcher for exception{" "}
            <span className="font-mono">{exceptionId.slice(0, 8)}</span>. Ground truth
            labels are never included.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          {evidence?.reason_code && (
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">
                Reason code
              </p>
              <Badge variant="secondary" className="font-mono text-[10px]">
                {evidence.reason_code}
              </Badge>
            </div>
          )}
          {evidence?.explanation && (
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">
                Deterministic explanation
              </p>
              <p className="text-xs">{evidence.explanation}</p>
            </div>
          )}
          {evidence?.normalized_utr && (
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">
                Normalized UTR
              </p>
              <p className="font-mono text-xs">{evidence.normalized_utr}</p>
            </div>
          )}
          {!!evidence?.related_settlement_transaction_ids?.length && (
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">
                Related settlements ({evidence.related_settlement_transaction_ids.length})
              </p>
              <ul className="space-y-1">
                {evidence.related_settlement_transaction_ids.map((id) => (
                  <li key={id} className="font-mono text-[11px] break-all">
                    {id}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <p className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">
              Raw evidence JSON
            </p>
            <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[10px] leading-relaxed">
              {JSON.stringify(evidence, null, 2)}
            </pre>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
