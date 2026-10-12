const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtInt(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString("en-US");
}

export function fmtUsdCompact(n: number): string {
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

/** "2026-02-17" -> "Feb 17, 2026"; anything else is returned unchanged. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

const NUMERIC = /^-?\d+(\.\d+)?$/;

export function isNumericLike(v: unknown): boolean {
  return typeof v === "number" || (typeof v === "string" && NUMERIC.test(v.trim()));
}

const MONEY_COLUMNS = /(usd|market_value|cost_basis|gain_loss|amount|aum|commitment|position|look_through)/i;

/** Formats a table cell: thousands separators that keep the source precision; money columns get "$". */
export function fmtCell(column: string, v: unknown): string {
  if (v == null || v === "") return "";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.map((x) => fmtCell(column, x)).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  if (isNumericLike(v) && !/(^id$|_id$|year|zip)/i.test(column)) {
    const s = String(v).trim();
    const decimals = s.includes(".") ? s.split(".")[1].length : 0;
    const num = Number(s);
    const shown = num.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    return MONEY_COLUMNS.test(column) && !/pct|weight/i.test(column) ? (num < 0 ? `-$${shown.slice(1)}` : `$${shown}`) : shown;
  }
  return String(v);
}

export function humanize(column: string): string {
  return column
    .replace(/_usd$/, " (USD)")
    .replace(/_pct$/, " (%)")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}
