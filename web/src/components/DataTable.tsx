import clsx from "clsx";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { fmtCell, humanize, isNumericLike } from "../lib/format";
import type { Row } from "../types";
import { useDocDrawer } from "./DocumentDrawer";

const DOC_ID = /^DOC-[A-Z]+-\d+$|^DOC-LIVE-[0-9A-F]+$/;
const WIDE = /(notes|summary|reason|description|evidence|title|strategy|registration|definition|meaning|examples|why|matches|body)/i;

export interface Column {
  key: string;
  label?: string;
  render?: (row: Row) => ReactNode;
  align?: "left" | "right" | "center";
  width?: number;
}

export function DataTable({
  rows,
  columns,
  pageSize = 25,
  searchable,
  maxHeight,
  dense = false,
  emptyText = "No rows.",
  toolbar,
}: {
  rows: Row[];
  columns?: Column[];
  pageSize?: number;
  searchable?: boolean;
  maxHeight?: number;
  dense?: boolean;
  emptyText?: string;
  toolbar?: ReactNode;
}) {
  const { open } = useDocDrawer();
  const cols: Column[] = useMemo(
    () => columns ?? (rows.length ? Object.keys(rows[0]).map((key) => ({ key })) : []),
    [columns, rows],
  );
  const numeric = useMemo(() => {
    const out: Record<string, boolean> = {};
    for (const c of cols) {
      const values = rows.map((r) => r[c.key]).filter((v) => v !== "" && v != null);
      out[c.key] = values.length > 0 && values.every(isNumericLike) && !/(^id$|_id$)/i.test(c.key);
    }
    return out;
  }, [cols, rows]);

  const showSearch = searchable ?? rows.length > 25;
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(pageSize);
  useEffect(() => {
    setPage(0);
  }, [rows, query, size]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = rows;
    if (q) out = rows.filter((r) => cols.some((c) => String(r[c.key] ?? "").toLowerCase().includes(q)));
    if (sort) {
      const k = sort.key;
      const num = numeric[k];
      out = [...out].sort((a, b) => {
        const va = a[k], vb = b[k];
        const cmp = num ? Number(va ?? 0) - Number(vb ?? 0) : String(va ?? "").localeCompare(String(vb ?? ""), undefined, { numeric: true });
        return sort.desc ? -cmp : cmp;
      });
    }
    return out;
  }, [rows, cols, query, sort, numeric]);

  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const visible = filtered.slice(page * size, page * size + size);

  const cell = (c: Column, r: Row): ReactNode => {
    if (c.render) return c.render(r);
    const v = r[c.key];
    if (typeof v === "string" && DOC_ID.test(v)) {
      return (
        <button type="button" onClick={() => open(v)} className="font-mono text-[12px] text-brand-700 hover:underline">
          {v}
        </button>
      );
    }
    if (typeof v === "string" && v.includes("|") && !WIDE.test(c.key)) {
      return (
        <span className="flex flex-wrap gap-1">
          {v.split("|").filter(Boolean).map((x) => (
            <span key={x} className="rounded bg-slate-100 px-1.5 py-px text-[11.5px] text-slate-600">{x}</span>
          ))}
        </span>
      );
    }
    return fmtCell(c.key, v);
  };

  return (
    <div className="flex flex-col gap-2.5">
      {(showSearch || toolbar) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {showSearch ? (
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter rows…"
                className="h-9 w-full rounded-lg border border-slate-200 bg-white pr-3 pl-8 text-[13px] shadow-sm outline-none placeholder:text-slate-400 focus:border-brand-400 focus:ring-3 focus:ring-brand-100"
              />
            </div>
          ) : <span />}
          <div className="flex items-center gap-3">
            {toolbar}
            <span className="text-[12px] text-slate-500 tabular-nums">
              {filtered.length.toLocaleString()} {filtered.length === 1 ? "row" : "rows"}
              {filtered.length !== rows.length && ` of ${rows.length.toLocaleString()}`}
            </span>
          </div>
        </div>
      )}
      <div className="scrollbar-thin overflow-auto rounded-lg border border-slate-200 bg-white" style={{ maxHeight }}>
        <table className="w-full border-separate border-spacing-0 text-[12.5px]">
          <thead className="sticky top-0 z-10">
            <tr>
              {cols.map((c) => {
                const active = sort?.key === c.key;
                const right = c.align === "right" || (c.align == null && numeric[c.key]);
                return (
                  <th
                    key={c.key}
                    onClick={() => setSort(active ? (sort!.desc ? null : { key: c.key, desc: true }) : { key: c.key, desc: false })}
                    className={clsx(
                      "cursor-pointer border-b border-slate-200 bg-slate-50 px-3 py-2 font-medium whitespace-nowrap text-slate-500 select-none hover:text-slate-800",
                      right ? "text-right" : "text-left",
                    )}
                    style={c.width ? { width: c.width } : undefined}
                  >
                    <span className={clsx("inline-flex items-center gap-1", right && "flex-row-reverse")}>
                      {c.label ?? humanize(c.key)}
                      {active && (sort!.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <tr key={i} className="group">
                {cols.map((c) => {
                  const right = c.align === "right" || (c.align == null && numeric[c.key]);
                  return (
                    <td
                      key={c.key}
                      className={clsx(
                        "border-b border-slate-100 px-3 align-top text-slate-700 group-last:border-b-0 group-hover:bg-slate-50/80",
                        dense ? "py-1.5" : "py-2",
                        right && "text-right tabular-nums whitespace-nowrap",
                        c.align === "center" && "text-center",
                        !right && (WIDE.test(c.key) ? "min-w-[260px]" : "whitespace-nowrap"),
                      )}
                    >
                      {cell(c, r)}
                    </td>
                  );
                })}
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={cols.length || 1} className="px-3 py-10 text-center text-slate-400">
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {filtered.length > size && (
        <div className="flex items-center justify-between text-[12px] text-slate-500">
          <div className="flex items-center gap-2">
            Rows per page
            <select
              value={size}
              onChange={(e) => setSize(Number(e.target.value))}
              className="rounded-md border border-slate-200 bg-white px-1.5 py-1 text-[12px]"
            >
              {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2 tabular-nums">
            Page {page + 1} of {pages}
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
              className="rounded-md border border-slate-200 bg-white p-1 disabled:opacity-40"
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              type="button"
              disabled={page >= pages - 1}
              onClick={() => setPage(page + 1)}
              className="rounded-md border border-slate-200 bg-white p-1 disabled:opacity-40"
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
