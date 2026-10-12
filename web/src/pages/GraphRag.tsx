import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, ChevronRight, ExternalLink, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../api";
import { Answer } from "../components/Answer";
import { CodeBlock } from "../components/CodeBlock";
import { GraphView } from "../components/GraphView";
import { PageHeader, useStatus } from "../components/Layout";
import { Button, ErrorState, LoadingBlock, TextInput, Toggle } from "../components/ui";
import { colorFor } from "../lib/colors";
import { fmtDate } from "../lib/format";
import { browserLink } from "../lib/neo4j";
import type { RagCompare, RagQuery, RagSide } from "../types";

interface Presets {
  questions: string[];
  llm: { available: boolean; model: string };
}

export function GraphRag() {
  const presets = useQuery({ queryKey: ["rag-presets"], queryFn: () => api.get<Presets>("/api/rag/presets") });
  const [question, setQuestion] = useState<string | null>(null);
  const [useLlm, setUseLlm] = useState(true);
  const [traversal, setTraversal] = useState(false);
  const ask = useMutation({ mutationFn: (b: { question: string; use_llm: boolean }) => api.post<RagCompare>("/api/rag", b) });
  const q = question ?? presets.data?.questions[0] ?? "";
  const llm = presets.data?.llm;
  const submit = () => {
    if (q.trim().length < 3) return;
    setTraversal(false);
    ask.mutate({ question: q.trim(), use_llm: !!llm?.available && useLlm });
  };
  const d = ask.data;

  return (
    <div>
      <PageHeader title="Graph-RAG">
        The same question, answered two ways: vector search over passages, and a traversal of the knowledge graph where every fact
        keeps its source.
      </PageHeader>

      <div className="flex flex-wrap gap-2">
        {presets.data?.questions.slice(0, 2).map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setQuestion(p)}
            className={clsx(
              "rounded-full border px-3.5 py-1.5 text-[13px] transition",
              p === q ? "border-brand-300 bg-brand-50 text-brand-800" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
            )}
          >
            {p}
          </button>
        ))}
      </div>
      <form className="mt-3 flex gap-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <TextInput value={q} onChange={(e) => setQuestion(e.target.value)} className="h-11 text-[14.5px]" placeholder="Ask about clients, investments, decisions…" />
        <Button variant="primary" type="submit" loading={ask.isPending} className="h-11 shrink-0 px-6">
          Ask
        </Button>
      </form>
      {llm?.available && (
        <div className="mt-3">
          <Toggle checked={useLlm} onChange={setUseLlm} label={`Write the answers with Claude (${llm.model})`} />
        </div>
      )}

      {ask.error && <div className="mt-6"><ErrorState error={ask.error} /></div>}
      {ask.isPending && <div className="mt-6"><LoadingBlock height={420} label="Searching the vector index and traversing the graph…" /></div>}
      {d && !ask.isPending && (
        <div className="mt-8 space-y-8">
          <div className="grid grid-cols-2 gap-6">
            <Side
              title="Standard RAG"
              subtitle={`Vector search · ${d.standard.chunks.length} similar passages`}
              side={d.standard}
            />
            <Side
              title="Graph-RAG"
              subtitle={`${d.strategy_label} · ${d.graph.facts.length} connected facts`}
              side={d.graph}
              accent
              linked={<Linked side={d.graph} />}
            />
          </div>

          {d.coverage.total > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white">
              <div className="grid grid-cols-[320px_1fr]">
                <div className="border-r border-slate-100 px-6 py-5">
                  <div className="text-[15px] font-semibold text-slate-900">What each approach could see</div>
                  <p className="mt-1 text-[13px] leading-relaxed text-slate-500">
                    The facts a complete answer needs. An LLM can only cite what it was given; some facts, like the current
                    look-through exposure, exist only as structured data.
                  </p>
                  <Bar label="Standard RAG" n={d.coverage.standard} total={d.coverage.total} color="#94a3b8" />
                  <Bar label="Graph-RAG" n={d.coverage.graph} total={d.coverage.total} color="#2f54d6" />
                </div>
                <div className="scrollbar-thin max-h-[420px] overflow-y-auto px-6 py-3">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="text-[11.5px] text-slate-400">
                        <th className="py-1.5 text-left font-medium">Fact</th>
                        <th className="w-28 py-1.5 font-medium">Standard</th>
                        <th className="w-28 py-1.5 font-medium">Graph</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.coverage.items.map((it) => (
                        <tr key={it.label} className="border-t border-slate-100">
                          <td className="py-1.5 pr-3 text-slate-700">{it.label}</td>
                          <td className="py-1.5 text-center"><Mark ok={it.standard} /></td>
                          <td className="py-1.5 text-center"><Mark ok={it.graph} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {d.graph.graph.nodes.length > 0 &&
            (traversal ? (
              <div>
                <div className="mb-2 text-[13px] font-medium text-slate-500">The part of the graph Graph-RAG walked</div>
                <GraphView graph={d.graph.graph} height={600} />
                {d.graph.queries.length > 0 && <CypherList queries={d.graph.queries} />}
              </div>
            ) : (
              <Button onClick={() => setTraversal(true)}>Show the traversal</Button>
            ))}
        </div>
      )}
    </div>
  );
}

function CypherList({ queries }: { queries: RagQuery[] }) {
  const browserUrl = useStatus().data?.browser_url;
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="mt-6">
      <div className="mb-2 text-[13px] font-medium text-slate-500">
        The Cypher behind it · {queries.length} {queries.length === 1 ? "query" : "queries"}, in the order they ran
      </div>
      <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
        {queries.map((q, i) => (
          <div key={i}>
            <button
              type="button"
              onClick={() => setOpen(open === i ? null : i)}
              className="flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-slate-50"
            >
              <span className="w-5 shrink-0 text-right text-[12px] text-slate-400 tabular-nums">{i + 1}</span>
              <span className={clsx("flex-1 text-[13.5px]", open === i ? "font-medium text-slate-900" : "text-slate-700")}>{q.purpose}</span>
              <span className="text-[12px] text-slate-400 tabular-nums">
                {q.rows.toLocaleString()} {q.kind === "graph" ? "nodes" : q.rows === 1 ? "row" : "rows"}
              </span>
              <ChevronRight className={clsx("size-4 shrink-0 text-slate-400 transition-transform", open === i && "rotate-90")} />
            </button>
            {open === i && (
              <div className="px-5 pt-1 pb-4 pl-[52px]">
                <CodeBlock code={q.browser_cypher} maxHeight={320} />
                {browserUrl && (
                  <a
                    href={browserLink(browserUrl, q.browser_cypher)}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-3 inline-flex h-9 items-center gap-1.5 rounded-lg bg-ink-900 px-3.5 text-[13px] font-medium text-white shadow-sm hover:bg-ink-800"
                  >
                    Open in Neo4j Browser <ExternalLink className="size-3.5" />
                  </a>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Side({ title, subtitle, side, accent, linked }: { title: string; subtitle: string; side: RagSide; accent?: boolean; linked?: ReactNode }) {
  return (
    <div className={clsx("flex h-[620px] flex-col rounded-xl border bg-white", accent ? "border-brand-200 shadow-[0_0_0_3px_rgba(63,104,239,0.06)]" : "border-slate-200")}>
      <div className="border-b border-slate-100 px-6 py-4">
        <div className={clsx("text-[15px] font-semibold", accent ? "text-brand-700" : "text-slate-900")}>{title}</div>
        <div className="mt-0.5 text-[12.5px] text-slate-500">{subtitle}</div>
        {linked}
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {side.warnings.map((w) => (
          <div key={w} className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[12.5px] text-amber-900">{w}</div>
        ))}
        <Answer text={side.answer} />
      </div>
    </div>
  );
}

function Linked({ side }: { side: RagSide }) {
  const mentions = side.linked.mentions ?? [];
  if (!mentions.length && !side.linked.since) return null;
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[12px] text-slate-500">
      Linked to
      {mentions.map((m) => (
        <span key={`${m.label}:${m.name}`} className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2 py-0.5 text-slate-700 ring-1 ring-slate-200">
          <span className="size-1.5 rounded-full" style={{ background: colorFor(m.label) }} />
          {m.name}
        </span>
      ))}
      {side.linked.since && (
        <span className="rounded-full bg-slate-50 px-2 py-0.5 text-slate-700 ring-1 ring-slate-200">
          since {fmtDate(String(side.linked.since))}
        </span>
      )}
    </div>
  );
}

function Bar({ label, n, total, color }: { label: string; n: number; total: number; color: string }) {
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="text-slate-600">{label}</span>
        <span className="text-[20px] font-semibold text-slate-900 tabular-nums">
          {n}
          <span className="text-[13px] font-normal text-slate-400">/{total}</span>
        </span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full" style={{ width: `${(100 * n) / total}%`, background: color }} />
      </div>
    </div>
  );
}

function Mark({ ok }: { ok: boolean }) {
  return ok ? <Check className="mx-auto size-4 text-emerald-600" /> : <X className="mx-auto size-4 text-rose-400" />;
}
