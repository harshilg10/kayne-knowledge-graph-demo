import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { api } from "../api";
import { DataTable } from "../components/DataTable";
import { DocumentView, DownloadOriginal } from "../components/DocumentDrawer";
import { PageHeader } from "../components/Layout";
import { ErrorState, LoadingBlock, Select, Tabs } from "../components/ui";
import { DOC_TYPE_COLORS } from "../lib/colors";
import { fmtDate, fmtInt } from "../lib/format";
import type { DocDetail, DocIndex, StructuredIndex, StructuredTable } from "../types";

export function SourceData() {
  const [tab, setTab] = useState<"structured" | "documents">("structured");
  const idx = useQuery({ queryKey: ["structured"], queryFn: () => api.get<StructuredIndex>("/api/structured") });
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.get<DocIndex>("/api/documents") });
  return (
    <div>
      <PageHeader title="Source data">
        Structured records say what happened. Documents say why. Today nothing joins them: a PDF has no foreign keys.
      </PageHeader>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "structured", label: "SQL data", count: idx.data?.systems.reduce((n, s) => n + s.tables.length, 0) },
          { value: "documents", label: "Documents", count: docs.data?.documents.length },
        ]}
      />
      <div className="mt-6">
        {tab === "structured"
          ? idx.error ? <ErrorState error={idx.error} /> : idx.data ? <Structured index={idx.data} /> : <LoadingBlock />
          : docs.error ? <ErrorState error={docs.error} /> : docs.data ? <Documents index={docs.data} /> : <LoadingBlock />}
      </div>
    </div>
  );
}

function Structured({ index }: { index: StructuredIndex }) {
  const [name, setName] = useState("clients.csv");
  const table = useQuery({
    queryKey: ["structured", name],
    queryFn: () => api.get<StructuredTable>(`/api/structured/${name}`),
    placeholderData: (prev) => prev,
  });
  const info = index.systems.flatMap((s) => s.tables).find((t) => t.name === name);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-5">
        <Select value={name} onChange={setName} className="w-[340px]">
          {index.systems.map((s) => (
            <optgroup key={s.system} label={s.system}>
              {s.tables.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name.replace(/\.csv$/, "")} · {fmtInt(t.rows)} rows
                </option>
              ))}
            </optgroup>
          ))}
        </Select>
        <span className="text-[13px] text-slate-500">{info?.description}</span>
      </div>
      {table.error ? (
        <ErrorState error={table.error} />
      ) : table.data ? (
        <DataTable key={name} rows={table.data.rows} columns={table.data.columns.map((key) => ({ key }))} maxHeight={600} dense />
      ) : (
        <LoadingBlock height={420} />
      )}
    </div>
  );
}

function Documents({ index }: { index: DocIndex }) {
  const [type, setType] = useState("All");
  const [selected, setSelected] = useState(index.hero_doc_id);
  const list = useMemo(() => index.documents.filter((d) => type === "All" || d.doc_type === type), [index, type]);
  const doc = useQuery({
    queryKey: ["document", selected],
    queryFn: () => api.get<DocDetail>(`/api/documents/${encodeURIComponent(selected)}`),
    placeholderData: (prev) => prev,
  });
  return (
    <div className="grid grid-cols-[360px_1fr] gap-6">
      <div className="flex max-h-[720px] min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-3">
          <Select value={type} onChange={setType}>
            <option value="All">All types · {index.documents.length}</option>
            {index.types.map((t) => (
              <option key={t} value={t}>
                {t} · {index.counts[t] ?? 0}
              </option>
            ))}
          </Select>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto">
          {list.map((d) => (
            <button
              key={d.doc_id}
              type="button"
              onClick={() => setSelected(d.doc_id)}
              className={clsx(
                "block w-full border-b border-slate-100 px-4 py-2.5 text-left last:border-0",
                selected === d.doc_id ? "bg-brand-50/70" : "hover:bg-slate-50",
              )}
            >
              <div className="flex items-center gap-2 text-[11.5px] text-slate-400">
                <span className="size-1.5 rounded-full" style={{ background: DOC_TYPE_COLORS[d.doc_type] }} />
                {d.doc_type} · {fmtDate(d.date)}
              </div>
              <div className={clsx("mt-0.5 text-[13px] leading-snug", selected === d.doc_id ? "font-medium text-brand-800" : "text-slate-700")}>
                {d.title}
              </div>
            </button>
          ))}
        </div>
      </div>
      <div className="min-w-0 rounded-xl border border-slate-200 bg-white px-8 py-7">
        {doc.error ? (
          <ErrorState error={doc.error} />
        ) : doc.data ? (
          <div className="relative">
            <div className="absolute top-0 right-0">
              <DownloadOriginal doc={doc.data} />
            </div>
            <DocumentView doc={doc.data} />
          </div>
        ) : (
          <LoadingBlock height={420} />
        )}
      </div>
    </div>
  );
}
