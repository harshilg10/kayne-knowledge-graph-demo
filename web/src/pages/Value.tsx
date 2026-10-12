import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { PageHeader } from "../components/Layout";
import { ErrorState, Skeleton } from "../components/ui";
import type { ValueCard } from "../types";

export function Value() {
  const data = useQuery({ queryKey: ["value"], queryFn: () => api.get<{ cards: ValueCard[] }>("/api/value") });
  return (
    <div>
      <PageHeader title="Business value">Each benefit, with its proof point computed from this graph.</PageHeader>
      {data.error && <ErrorState error={data.error} />}
      <div className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
        {data.data
          ? data.data.cards.map((c, i) => (
              <div key={c.title} className="grid grid-cols-[48px_300px_1fr] items-baseline gap-4 px-6 py-5">
                <span className="text-[13px] font-medium text-slate-400 tabular-nums">0{i + 1}</span>
                <div>
                  <div className="text-[16px] font-semibold tracking-tight text-slate-900">{c.title}</div>
                  <div className="mt-0.5 text-[13.5px] text-slate-500">{c.claim}</div>
                </div>
                <div className="text-[14px] leading-relaxed text-slate-600">{c.proof}</div>
              </div>
            ))
          : !data.error && [0, 1, 2, 3, 4].map((i) => <div key={i} className="px-6 py-5"><Skeleton className="h-10" /></div>)}
      </div>
      <p className="mt-10 max-w-[900px] text-[20px] leading-relaxed font-medium tracking-tight text-slate-800">
        The semantic model is the investment. Once it exists, every new source plugs into the same vocabulary, identities and rules,
        and every AI use case (Copilot, Graph-RAG, search) is grounded in it.
      </p>
    </div>
  );
}
