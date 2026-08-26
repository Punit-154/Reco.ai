import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPct } from "@/lib/format";
import type { RunSummaryData } from "@/lib/api/types";

interface Props {
  summary: RunSummaryData | null;
}

export default function DashboardMetrics({ summary }: Props) {
  const items = [
    { label: "Bank transactions", value: summary?.total_bank_transactions ?? "—" },
    { label: "Auto-matched", value: summary?.matched_bank_transactions ?? "—" },
    { label: "Unmatched", value: summary?.unmatched_bank_transactions ?? "—" },
    {
      label: "Deterministic match rate",
      value: formatPct(summary?.deterministic_match_rate),
    },
    { label: "Exceptions", value: summary?.exceptions_total ?? "—" },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
      {items.map((item) => (
        <Card key={item.label} className="py-3">
          <CardHeader className="px-3 pb-1">
            <CardTitle className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              {item.label}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3">
            <div className="font-mono text-xl font-semibold tabular-nums">
              {item.value}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
