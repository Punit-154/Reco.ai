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
      iconColor: "text-success",
      cardClass: "border-success/20 bg-success/5",
    },
    {
      label: "Exceptions",
      value: summary?.exceptions_total ?? "—",
      icon: AlertTriangle,
      iconColor: "text-destructive",
      cardClass: "border-destructive/20 bg-destructive/5",
    },
    {
      label: "Deterministic Rate",
      value: summary ? formatPct(summary.deterministic_match_rate) : "—",
      icon: BarChart3,
      iconColor: "text-primary",
      cardClass: "border-primary/20 bg-primary/5",
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
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label} className={`shadow-card ${stat.cardClass}`}>
            <CardContent className="flex items-center gap-3.5 pt-5 pb-4 px-5">
              <stat.icon className={`size-8 shrink-0 ${stat.iconColor}`} />
              <div>
                <div className="font-mono text-2xl font-bold tabular-nums tracking-tight">{stat.value}</div>
                <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase mt-1">
                  {stat.label}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span>Unmatched: {summary?.unmatched_bank_transactions ?? "—"}</span>
        <span>Exceptions by category: {categoryBreakdown}</span>
      </div>
    </div>
  );
}
