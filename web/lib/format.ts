export const DEMO_ACTOR = "demo_finance_controller";
export const DEMO_MODE_LABEL = "Demo mode — single reviewer";

export function formatPaise(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  const negative = paise < 0;
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.floor(abs / 100);
  const paisa = abs % 100;
  return `${negative ? "-" : ""}₹${rupees.toLocaleString("en-IN")}.${String(paisa).padStart(2, "0")}`;
}

export function formatPct(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { hour12: false });
}
