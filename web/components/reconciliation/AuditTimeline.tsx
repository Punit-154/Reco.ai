"use client";

import { useEffect, useMemo, useState } from "react";
import { History } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listAuditLogs } from "@/lib/api/client";
import type { AuditEvent } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

export default function AuditTimeline({
  exceptionId,
  statusFilter = "all",
  version = 0,
}: {
  exceptionId?: string;
  statusFilter?: string;
  version?: number;
}) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listAuditLogs({
      entity_type: "exception",
      ...(exceptionId ? { entity_id: exceptionId } : {}),
    })
      .then((logs) => {
        if (active) setEvents(logs);
      })
      .catch((e) => {
        if (active) setError(String(e.message ?? e));
      });
    return () => {
      active = false;
    };
  }, [exceptionId, version]);

  const filtered = useMemo(() => {
    if (statusFilter === "all") return events;
    return events.filter((e) => e.new_state?.status === statusFilter);
  }, [events, statusFilter]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1 text-sm">
          <History className="size-3.5" /> Audit timeline
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && <p className="text-xs text-red-600">{error}</p>}
        {filtered.length === 0 && !error && (
          <p className="text-xs text-muted-foreground">No human actions recorded yet.</p>
        )}
        <ol className="space-y-2">
          {filtered.map((event) => (
            <li key={event.id} className="border-l-2 pl-3 text-xs">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono text-[10px]">
                  {event.action}
                </Badge>
                <span className="text-muted-foreground">
                  {formatDateTime(event.created_at)}
                </span>
              </div>
              {event.reason && <p className="mt-0.5">Reason: {event.reason}</p>}
              {event.ai_hypothesis && (
                <p className="mt-0.5 text-muted-foreground">
                  AI hypothesis preserved:{" "}
                  {String(
                    (event.ai_hypothesis as { category?: string }).category ?? "n/a"
                  )}
                  {" · "}
                  confidence {String((event.ai_hypothesis as { confidence?: number }).confidence ?? "—")}
                </p>
              )}
              <p className="mt-0.5 text-muted-foreground">
                {String(event.previous_state?.status ?? "—")} →{" "}
                {String(event.new_state?.status ?? "—")}
              </p>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
