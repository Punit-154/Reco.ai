"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

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
import { getRunMatches } from "@/lib/api/client";
import type { MatchGroupRow } from "@/lib/api/types";
import { formatPaise } from "@/lib/format";

const STRATEGY_VARIANT: Record<
  string,
  "default" | "secondary" | "outline"
> = {
  EXACT_UTR_AMOUNT: "default",
  AMOUNT_DATE_WINDOW: "secondary",
  LEDGER_NET_EXACT: "outline",
};

export default function MatchTable({ runId }: { runId: string }) {
  const [groups, setGroups] = useState<MatchGroupRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    getRunMatches(runId)
      .then(setGroups)
      .catch((e) => setError(String(e.message ?? e)));
  }, [runId]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Match groups</CardTitle>
        <CardDescription className="text-xs">
          Deterministic matches with rule-linked members ({groups.length})
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className="text-xs text-red-600">{error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-8 text-xs">Group</TableHead>
              <TableHead className="h-8 text-xs">Strategy</TableHead>
              <TableHead className="h-8 text-xs">Expected</TableHead>
              <TableHead className="h-8 text-xs">Actual</TableHead>
              <TableHead className="h-8 text-xs">Delta</TableHead>
              <TableHead className="h-8 text-xs">Members</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((group) => (
              <>
                <TableRow
                  key={group.group_id}
                  className="cursor-pointer"
                  onClick={() => setExpanded((p) => (p === group.group_id ? null : group.group_id))}
                >
                  <TableCell className="py-1.5 font-mono text-[11px]">
                    {group.group_id.slice(0, 8)}
                  </TableCell>
                  <TableCell className="py-1.5">
                    <Badge variant={STRATEGY_VARIANT[group.strategy] ?? "secondary"}>
                      {group.strategy}
                    </Badge>
                    {expanded === group.group_id
                      ? <ChevronDown className="size-3 inline ml-1 text-muted-foreground" />
                      : <ChevronRight className="size-3 inline ml-1 text-muted-foreground" />}
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    {formatPaise(group.expected_amount_paise)}
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    {formatPaise(group.actual_amount_paise)}
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-xs tabular-nums">
                    {(group.delta_paise ?? 0) === 0 ? (
                      "0"
                    ) : (
                      <span className="text-red-600">{formatPaise(group.delta_paise)}</span>
                    )}
                  </TableCell>
                  <TableCell className="py-1.5">
                    <div className="flex flex-wrap gap-1">
                      {group.members.map((member) => (
                        <span
                          key={member.transaction_id}
                          className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]"
                          title={`${member.role} · ${formatPaise(member.amount_paise)}`}
                        >
                          {member.external_id}
                        </span>
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
                {expanded === group.group_id && (
                  <TableRow key={`${group.group_id}-trace`}>
                    <TableCell colSpan={6} className="p-0 px-2 pb-2">
                      <div className="rounded bg-muted/40 border mt-0.5 p-2.5 text-[10px] font-mono space-y-1.5">
                        <p className="text-xs font-semibold text-foreground">
                          ✓ Matched via {group.strategy}
                          {group.deterministic_score != null && ` · score ${group.deterministic_score.toFixed(3)}`}
                        </p>
                        {group.rule_trace && Object.keys(group.rule_trace).length > 0 ? (
                          <div className="grid grid-cols-[180px_1fr] gap-x-3 gap-y-0.5">
                            {Object.entries(group.rule_trace).map(([k, v]) => (
                              <>
                                <span key={k + "_k"} className="text-muted-foreground capitalize">
                                  {k.replace(/_/g, " ")}
                                </span>
                                <span key={k + "_v"} className="break-all">{String(v)}</span>
                              </>
                            ))}
                          </div>
                        ) : (
                          <p className="text-muted-foreground">No rule trace stored.</p>
                        )}
                        <div className="border-t pt-1 text-[9px] text-muted-foreground">
                          Members:{" "}
                          {group.members
                            .map((m) => `[${m.role}] ${m.external_id} ₹${(m.amount_paise / 100).toFixed(2)}`)
                            .join(" · ")}
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
