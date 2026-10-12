import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Fragment } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useStatus } from "../components/Layout";
import { fmtInt, fmtUsdCompact } from "../lib/format";
import type { Overview as OverviewData } from "../types";

const PIPELINE = ["Sources", "Ingest", "Extract", "Semantic mapping", "Knowledge graph", "Cypher & Graph-RAG"];

export function Overview() {
  const hero = useStatus().data?.hero;
  const data = useQuery({ queryKey: ["overview"], queryFn: () => api.get<OverviewData>("/api/overview") }).data;
  const stats: [string, string][] = data
    ? [
        ["Clients", fmtInt(data.book.clients)],
        ["Assets under management", fmtUsdCompact(data.book.aum_usd)],
        ["Documents", fmtInt(data.book.documents)],
        ["Graph nodes · relationships", data.graph.ok ? `${fmtInt(data.graph.nodes)} · ${fmtInt(data.graph.rels)}` : "offline"],
      ]
    : [];
  return (
    <div className="pt-6">
      <div className="text-[12px] font-semibold tracking-[0.12em] text-brand-600 uppercase">The question</div>
      <h1 className="mt-4 max-w-[1000px] text-[38px] leading-[1.18] font-semibold tracking-tight text-slate-900">
        “Show me everything related to <span className="text-brand-600">AI infrastructure</span> investments that impacted the{" "}
        <span className="text-amber-600">{hero?.client_name ?? "Hartwell Family Trust"}</span> in the last 12 months.”
      </h1>
      <p className="mt-5 max-w-[760px] text-[16px] leading-relaxed text-slate-500">
        The answer is spread across portfolio accounting, trading, CRM, email, meeting notes, research and due-diligence files.
        A semantic model turns all of it into one connected graph.
      </p>

      <div className="mt-10 flex flex-wrap items-center gap-x-3 gap-y-2 text-[14px]">
        {PIPELINE.map((step, i) => (
          <Fragment key={step}>
            <span className="rounded-full border border-slate-200 bg-white px-3.5 py-1.5 font-medium text-slate-700 shadow-sm">{step}</span>
            {i < PIPELINE.length - 1 && <ArrowRight className="size-4 text-slate-300" />}
          </Fragment>
        ))}
      </div>

      <div className="mt-12 grid grid-cols-4 divide-x divide-slate-200 rounded-xl border border-slate-200 bg-white">
        {(stats.length ? stats : [["", ""], ["", ""], ["", ""], ["", ""]]).map(([label, value], i) => (
          <div key={i} className="px-6 py-5">
            <div className="text-[12.5px] text-slate-500">{label || " "}</div>
            <div className="mt-1 h-9 text-[28px] font-semibold tracking-tight text-slate-900 tabular-nums">{value}</div>
          </div>
        ))}
      </div>

      <Link
        to="/data"
        className="mt-10 inline-flex h-11 items-center gap-2 rounded-lg bg-ink-900 px-5 text-[14px] font-medium text-white shadow-sm hover:bg-ink-800"
      >
        Start with the source data <ArrowRight className="size-4" />
      </Link>
    </div>
  );
}
