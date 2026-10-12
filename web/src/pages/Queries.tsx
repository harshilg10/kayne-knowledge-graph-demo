import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { DataTable } from "../components/DataTable";
import { GraphView } from "../components/GraphView";
import { PageHeader } from "../components/Layout";
import { ErrorState, LoadingBlock, Segmented } from "../components/ui";
import { humanize } from "../lib/format";
import { browserLink } from "../lib/neo4j";
import type { QueryDef, QueryResult } from "../types";

export function Queries() {
  const list = useQuery({ queryKey: ["queries"], queryFn: () => api.get<{ queries: QueryDef[]; browser_url: string }>("/api/queries") });
  const [id, setId] = useState("brief-1-theme-documents");
  const groups = useMemo(() => {
    const g: Record<string, QueryDef[]> = {};
    for (const q of list.data?.queries ?? []) (g[q.group] ??= []).push(q);
    return g;
  }, [list.data]);
  const q = list.data?.queries.find((x) => x.id === id);
  return (
    <div>
      <PageHeader title="Graph queries">
        Questions that need several hops across systems. Each one runs here, and opens in Neo4j Browser with one click.
      </PageHeader>
      {list.error && <ErrorState error={list.error} />}
      {list.data && (
        <div className="grid grid-cols-[260px_1fr] gap-8">
          <nav className="space-y-5">
            {Object.entries(groups).map(([group, qs]) => (
              <div key={group}>
                <div className="mb-1.5 px-3 text-[11px] font-semibold tracking-[0.08em] text-slate-400 uppercase">{group}</div>
                {qs.map((x) => (
                  <button
                    key={x.id}
                    type="button"
                    onClick={() => setId(x.id)}
                    className={clsx(
                      "block w-full rounded-lg px-3 py-2 text-left text-[13.5px] leading-snug transition",
                      x.id === id ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-50",
                    )}
                  >
                    {x.title.replace(/ -> /g, " → ")}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          {q && <QueryPanel key={q.id} q={q} browserUrl={list.data.browser_url} />}
        </div>
      )}
    </div>
  );
}

function QueryPanel({ q, browserUrl }: { q: QueryDef; browserUrl: string }) {
  const run = useQuery({
    queryKey: ["query-run", q.id],
    queryFn: () => api.post<QueryResult>(`/api/queries/${q.id}/run`, { params: {} }),
  });
  const [view, setView] = useState<"table" | "graph">("table");
  const r = run.data;
  const both = !!(r?.rows && r.graph);
  return (
    <div className="min-w-0">
      <div className="flex items-start justify-between gap-6">
        <div className="text-[17px] leading-snug font-medium text-slate-900">{q.question}</div>
        <a
          href={browserLink(browserUrl, q.browser_cypher)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-ink-900 px-3.5 text-[13px] font-medium text-white shadow-sm hover:bg-ink-800"
        >
          Open in Neo4j Browser <ExternalLink className="size-3.5" />
        </a>
      </div>
      <CodeBlock code={q.cypher} className="mt-4" maxHeight={260} />
      <div className="mt-6">
        {run.error ? (
          <ErrorState error={run.error} />
        ) : !r ? (
          <LoadingBlock height={360} label="Running Cypher…" />
        ) : (
          <div>
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[12.5px] text-slate-500">
                {r.rows ? `${r.rows.length.toLocaleString()} rows` : `${r.graph?.nodes.length} nodes · ${r.graph?.edges.length} relationships`} ·{" "}
                {r.ms} ms
              </span>
              {both && (
                <Segmented size="sm" value={view} onChange={setView} options={[{ value: "table", label: "Table" }, { value: "graph", label: "Graph" }]} />
              )}
            </div>
            {r.rows && (!r.graph || view === "table") && (
              <DataTable rows={r.rows} columns={(r.columns ?? []).map((key) => ({ key, label: humanize(key) }))} maxHeight={520} searchable={r.rows.length > 25} />
            )}
            {r.graph && (!r.rows || view === "graph") && <GraphView graph={r.graph} height={560} />}
          </div>
        )}
      </div>
    </div>
  );
}
