import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ExternalLink } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import { GraphView } from "../components/GraphView";
import { PageHeader, useStatus } from "../components/Layout";
import { Button, ErrorState, LoadingBlock, Segmented, Select } from "../components/ui";
import { colorFor } from "../lib/colors";
import { fmtDate } from "../lib/format";
import { browserLink } from "../lib/neo4j";
import type { ExtractEntity, ExtractResult, ExtractSources, Graph } from "../types";

function highlight(text: string, entities: ExtractEntity[]): ReactNode[] {
  const spans: { s: number; t: number; e: ExtractEntity }[] = [];
  for (const e of entities) for (const [s, t] of e.spans) spans.push({ s, t, e });
  spans.sort((a, b) => a.s - b.s || b.t - b.s - (a.t - a.s));
  const out: ReactNode[] = [];
  let pos = 0;
  spans.forEach(({ s, t, e }, i) => {
    if (s < pos) return;
    out.push(text.slice(pos, s));
    const c = colorFor(e.label);
    out.push(
      <mark key={i} title={`${e.label}: ${e.name}`} className="rounded-[3px] px-0.5 text-slate-900" style={{ background: `${c}30`, boxShadow: `inset 0 -2px 0 ${c}` }}>
        {text.slice(s, t)}
      </mark>,
    );
    pos = t;
  });
  out.push(text.slice(pos));
  return out;
}

export function Extract() {
  const qc = useQueryClient();
  const status = useStatus().data;
  const sources = useQuery({ queryKey: ["extract-sources"], queryFn: () => api.get<ExtractSources>("/api/extract/sources") });
  const [paste, setPaste] = useState(false);
  const [docId, setDocId] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [engine, setEngine] = useState<string | null>(null);
  const s = sources.data;
  const body = paste
    ? { text: text ?? s?.paste_sample ?? "", engine: engine ?? s?.engines[0] ?? "rules" }
    : { doc_id: docId ?? s?.default_doc_id ?? "", engine: engine ?? s?.engines[0] ?? "rules" };

  const extract = useMutation({ mutationFn: (b: typeof body) => api.post<ExtractResult>("/api/extract", b) });
  const write = useMutation({
    mutationFn: (b: typeof body) => api.post<{ doc_id: string }>("/api/extract/write", b),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["status"] }),
  });
  const r = extract.data;
  const written = !!r && write.data?.doc_id === r.doc_id;
  const context = useQuery({
    queryKey: ["doc-in-graph", r?.doc_id, written],
    queryFn: () => api.get<Graph>(`/api/documents/${encodeURIComponent(r!.doc_id)}/graph`),
    enabled: !!r && (r.in_graph || written),
  });
  const grouped = useMemo(() => {
    const g: Record<string, ExtractSources["documents"]> = {};
    for (const d of s?.documents ?? []) (g[d.doc_type] ??= []).push(d);
    return g;
  }, [s]);

  return (
    <div>
      <PageHeader title="Unstructured → graph">
        The semantic model constrains extraction: every entity resolves to a known identity, every relationship must be allowed by
        the ontology, and business words map to themes.
      </PageHeader>
      {sources.error && <ErrorState error={sources.error} />}
      {s && (
        <div>
          <div className="flex flex-wrap items-center gap-3">
            {!paste && (
              <Select value={body.doc_id ?? ""} onChange={setDocId} className="min-w-[440px] flex-1">
                {Object.entries(grouped).map(([type, docs]) => (
                  <optgroup key={type} label={type}>
                    {docs.map((d) => (
                      <option key={d.doc_id} value={d.doc_id}>
                        {d.title} · {fmtDate(d.date)}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </Select>
            )}
            {s.engines.length > 1 && (
              <Segmented
                value={body.engine}
                onChange={setEngine}
                options={s.engines.map((e) => ({ value: e, label: e === "claude" ? "Claude" : "Rules engine" }))}
              />
            )}
            <Button variant="primary" loading={extract.isPending} onClick={() => { write.reset(); extract.mutate(body); }}>
              Extract
            </Button>
            <button type="button" onClick={() => setPaste(!paste)} className="text-[13px] font-medium text-brand-700 hover:text-brand-800">
              {paste ? "Pick a document instead" : "or paste a note"}
            </button>
          </div>
          {paste && (
            <textarea
              value={body.text}
              onChange={(e) => setText(e.target.value)}
              rows={9}
              spellCheck={false}
              className="mt-3 w-full rounded-xl border border-slate-200 bg-white p-4 font-mono text-[12.5px] leading-relaxed outline-none focus:border-brand-400 focus:ring-3 focus:ring-brand-100"
            />
          )}
        </div>
      )}

      {extract.error && <div className="mt-6"><ErrorState error={extract.error} /></div>}
      {extract.isPending && !r && <div className="mt-6"><LoadingBlock height={380} label="Extracting…" /></div>}
      {r && (
        <div className="mt-7 space-y-8">
          {r.warnings.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900">{r.warnings.join(" ")}</div>
          )}
          <div className="grid grid-cols-2 gap-6">
            <div className="min-w-0">
              <Label>The note</Label>
              <div className="scrollbar-thin max-h-[460px] overflow-y-auto rounded-xl border border-slate-200 bg-white px-5 py-4">
                <div className="doc-text">{highlight(r.record.text, r.entities)}</div>
              </div>
            </div>
            <div className="min-w-0">
              <Label>
                {r.entities.length} entities · {r.relationships.length} relationships
              </Label>
              <GraphView graph={r.graph} height={418} highlightIds={[`Document:${r.doc_id}`]} />
            </div>
          </div>

          <div>
            <Label>Relationships, each checked against the ontology</Label>
            <div className="grid grid-cols-2 gap-x-6 rounded-xl border border-slate-200 bg-white px-5 py-2">
              {r.relationships.map((rel, i) => (
                <div key={i} className="flex items-center gap-2 border-b border-slate-100 py-2 text-[13px] [&:nth-last-child(-n+2)]:border-0">
                  <span className="truncate text-slate-700">{rel.source.replace(/ \((.*)\)$/, "")}</span>
                  <ArrowRight className="size-3 shrink-0 text-slate-300" />
                  <span className="shrink-0 font-mono text-[11.5px] font-semibold text-brand-700">{rel.type}</span>
                  <ArrowRight className="size-3 shrink-0 text-slate-300" />
                  <span className="truncate text-slate-700">{rel.target.replace(/ \((.*)\)$/, "")}</span>
                  {rel.inferred && <span className="ml-auto shrink-0 rounded-full bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">via {rel.via}</span>}
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-3 flex items-center gap-3">
              {written ? (
                <span className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-emerald-700">
                  <CheckCircle2 className="size-4" /> Written to Neo4j
                </span>
              ) : (
                <Button variant="primary" loading={write.isPending} onClick={() => write.mutate(body)}>
                  Write to the knowledge graph
                </Button>
              )}
              {context.data?.browser_cypher && status && (
                <a
                  href={browserLink(status.browser_url, context.data.browser_cypher)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
                >
                  Open in Neo4j Browser <ExternalLink className="size-3.5" />
                </a>
              )}
            </div>
            {write.error && <ErrorState error={write.error} compact />}
            {context.data ? (
              <>
                <Label>This note in the knowledge graph: who was there, what it is about, and how it reaches the Hartwell portfolio</Label>
                <GraphView graph={context.data} height={480} highlightIds={context.data.nodes.filter((n) => n.properties.id === r.doc_id).map((n) => n.id)} />
              </>
            ) : context.isFetching ? (
              <LoadingBlock height={300} />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-2 text-[13px] font-medium text-slate-500">{children}</div>;
}
