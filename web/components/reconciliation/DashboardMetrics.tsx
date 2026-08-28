import { Card, CardContent } from "@/components/ui/card";
import { formatPct } from "@/lib/format";
import type { RunSummaryData } from "@/lib/api/types";
import { CheckCircle2, AlertTriangle, BarChart3, Database } from "lucide-react";

interface Props {
  summary: RunSummaryData | null;
}

export default function DashboardMetrics({ summary }: Props) {
  const stats = [
    {
      label: "Auto-Matched",
      value: summary?.matched_bank_transactions ?? "—",
      icon: CheckCircle2,
      iconColor: "text-green-600",
      cardClass: "border-green-200 bg-green-50/40",
    },
    {
      label: "Exceptions",
      value: summary?.exceptions_total ?? "—",
      icon: AlertTriangle,
      iconColor: "text-red-500",
      cardClass: "border-red-200 bg-red-50/40",
    },
    {
      label: "Deterministic Rate",
      value: summary ? formatPct(summary.deterministic_match_rate) : "—",
      icon: BarChart3,
      iconColor: "text-blue-600",
      cardClass: "border-blue-200 bg-blue-50/40",
    },
    {
      label: "Total Transactions",
      value: summary?.total_bank_transactions ?? "—",
      icon: Database,
      iconColor: "text-muted-foreground",
      cardClass: "",
    },
  ];

  const categoryBreakdown = Object.entries(summary?.exceptions_by_category ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join(" · ") || "—";

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label} className={stat.cardClass}>
            <CardContent className="flex items-center gap-3 pt-4 pb-3 px-4">
              <stat.icon className={`size-7 shrink-0 ${stat.iconColor}`} />
              <div>
                <div className="font-mono text-2xl font-bold tabular-nums">{stat.value}</div>
                <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase mt-0.5">
                  {stat.label}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>Unmatched: {summary?.unmatched_bank_transactions ?? "—"}</span>
        <span>Exceptions by category: {categoryBreakdown}</span>
      </div>
    </div>
  );
}
