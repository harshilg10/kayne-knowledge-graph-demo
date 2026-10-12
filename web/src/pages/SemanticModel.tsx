import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { DataTable } from "../components/DataTable";
import { GraphView } from "../components/GraphView";
import { PageHeader } from "../components/Layout";
import { ErrorState, LoadingBlock, Tabs } from "../components/ui";
import { colorFor } from "../lib/colors";
import { fmtDate } from "../lib/format";
import type { KeywordVsSemantic, ModelPayload } from "../types";

type Tab = "ontology" | "vocabulary" | "compare";

export function SemanticModel() {
  const [tab, setTab] = useState<Tab>("ontology");
  const model = useQuery({ queryKey: ["model"], queryFn: () => api.get<ModelPayload>("/api/model") });
  return (
    <div>
      <PageHeader title="Semantic model">
        The business vocabulary and ontology: what things are, how they relate, and what words mean. Without it you are searching
        text; with it you understand meaning.
      </PageHeader>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "ontology", label: "Ontology" },
          { value: "vocabulary", label: "Vocabulary" },
          { value: "compare", label: "Keyword search vs meaning" },
        ]}
      />
      <div className="mt-6">
        {tab === "compare" ? (
          <Compare />
        ) : model.error ? (
          <ErrorState error={model.error} />
        ) : !model.data ? (
          <LoadingBlock />
        ) : tab === "ontology" ? (
          <div>
            <GraphView graph={model.data.schema} height={600} legend={false} />
            <div className="mt-3 flex gap-6 text-[12.5px] text-slate-500">
              <span>Solid: loaded from systems of record or extracted from text</span>
              <span>Dashed: derived by a business rule (e.g. a client owns a fund through its accounts)</span>
            </div>
          </div>
        ) : (
          <Vocabulary model={model.data} />
        )}
      </div>
    </div>
  );
}

function Vocabulary({ model }: { model: ModelPayload }) {
  const [id, setId] = useState("THM-AI");
  const theme = model.themes.find((t) => t.id === id) ?? model.themes[0];
  return (
    <div className="grid grid-cols-[280px_1fr] gap-8">
      <div className="flex flex-col">
        {model.themes.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setId(t.id)}
            className={clsx(
              "flex items-center justify-between rounded-lg px-3 py-2 text-left text-[13.5px] transition",
              t.id === theme.id ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-50",
            )}
          >
            {t.name}
            <span className="text-[11.5px] text-slate-400 tabular-nums">{t.concepts.length}</span>
          </button>
        ))}
      </div>
      <div>
        <div className="flex items-center gap-2.5">
          <span className="size-3 rounded-full" style={{ background: colorFor("Theme") }} />
          <h2 className="text-[20px] font-semibold tracking-tight text-slate-900">{theme.name}</h2>
        </div>
        <p className="mt-1.5 text-[14px] text-slate-500">{theme.definition}</p>
        <p className="mt-1 text-[13px] text-slate-400">Also written as: {theme.synonyms.join(", ")}</p>
        <div className="mt-6 text-[12px] font-semibold tracking-wide text-slate-500 uppercase">
          What people write → what the business means
        </div>
        <div className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {theme.concepts.map((c) => (
            <div key={c.name} className="grid grid-cols-[1fr_auto_200px] items-center gap-4 px-5 py-3">
              <div>
                <div className="text-[14px] font-medium text-slate-800">{c.name}</div>
                <div className="mt-0.5 text-[12.5px] text-slate-400">{c.synonyms.join(", ")}</div>
              </div>
              <ArrowRight className="size-4 text-slate-300" />
              <span className="inline-flex items-center gap-2 text-[13px] font-medium text-slate-700">
                <span className="size-2 rounded-full" style={{ background: colorFor("Theme") }} />
                {theme.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Compare() {
  const q = useQuery({ queryKey: ["keyword-vs-semantic"], queryFn: () => api.get<KeywordVsSemantic>("/api/model/keyword-vs-semantic") });
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return <LoadingBlock />;
  const d = q.data;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 divide-x divide-slate-200 rounded-xl border border-slate-200 bg-white">
        <Num label={`Keyword search: “${d.phrase}”`} value={String(d.keyword_total)} />
        <Num label="Semantic model: AI Infrastructure theme" value={String(d.semantic_total)} accent />
        <Num label="Found only through the semantic model" value={`+${d.missed_total}`} green />
      </div>
      <div>
        <div className="mb-3 text-[14px] font-medium text-slate-800">
          The {d.missed_total} documents keyword search misses, and the concept that connected each one
        </div>
        <DataTable
          rows={d.missed as unknown as Record<string, unknown>[]}
          pageSize={10}
          searchable={false}
          columns={[
            { key: "date", render: (r) => fmtDate(String(r.date)) },
            { key: "title", label: "Document" },
            { key: "type" },
            {
              key: "via",
              label: "Matched through",
              render: (r) => (
                <span className="flex flex-wrap gap-1">
                  {(r.via as string[]).map((v) => (
                    <span key={v} className="rounded-full bg-rose-50 px-2 py-0.5 text-[12px] font-medium text-rose-700">{v}</span>
                  ))}
                </span>
              ),
            },
            { key: "doc_id", label: "" },
          ]}
        />
      </div>
    </div>
  );
}

function Num({ label, value, accent, green }: { label: string; value: string; accent?: boolean; green?: boolean }) {
  return (
    <div className="px-6 py-5">
      <div className="text-[12.5px] text-slate-500">{label}</div>
      <div className={clsx("mt-1 text-[34px] font-semibold tracking-tight tabular-nums", accent ? "text-brand-600" : green ? "text-emerald-600" : "text-slate-900")}>
        {value}
      </div>
    </div>
  );
}
