import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDate } from "../lib/format";
import { STEPS } from "../steps";
import type { Status } from "../types";

export function useStatus() {
  return useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/api/status"), refetchInterval: 15000 });
}

/** ← / → (or a presentation clicker's PageUp / PageDown) move between steps. */
function useStepKeys() {
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector('[role="dialog"]')) return;
      const i = STEPS.findIndex((s) => s.path === location.pathname);
      if (i < 0) return;
      if ((e.key === "ArrowRight" || e.key === "PageDown") && i < STEPS.length - 1) navigate(STEPS[i + 1].path);
      if ((e.key === "ArrowLeft" || e.key === "PageUp") && i > 0) navigate(STEPS[i - 1].path);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [location.pathname, navigate]);
}

function TopBar() {
  const status = useStatus().data;
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-8 px-8">
        <Link to="/" className="flex shrink-0 items-center gap-2.5">
          <img src="/favicon.svg" alt="" className="size-7 rounded-md" />
          <span className="text-[14px] font-semibold tracking-tight text-slate-900">Knowledge Graph</span>
        </Link>
        <nav className="flex flex-1 items-center gap-1">
          {STEPS.slice(1).map((s) => (
            <NavLink
              key={s.path}
              to={s.path}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13.5px] transition-colors",
                  isActive ? "bg-slate-100 font-medium text-slate-900" : "text-slate-500 hover:text-slate-900",
                )
              }
            >
              <span className="text-[11px] text-slate-400 tabular-nums">{s.number}</span>
              {s.nav}
            </NavLink>
          ))}
        </nav>
        {status && (
          <div className="flex shrink-0 items-center gap-4 text-[12.5px]">
            <span className="flex items-center gap-1.5 text-slate-500">
              <span className={clsx("size-1.5 rounded-full", status.neo4j.ok ? "bg-emerald-500" : "bg-rose-500")} />
              {status.neo4j.ok ? "Neo4j connected" : "Neo4j offline"}
            </span>
            {status.neo4j.ok && (
              <a href={status.browser_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 font-medium text-brand-700 hover:text-brand-800">
                Neo4j Browser <ExternalLink className="size-3.5" />
              </a>
            )}
          </div>
        )}
      </div>
    </header>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  useStepKeys();
  const location = useLocation();
  const status = useStatus().data;
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <main className="mx-auto w-full max-w-[1280px] flex-1 px-8 pt-8 pb-12">{children}</main>
      {status && (
        <footer className="mx-auto w-full max-w-[1280px] px-8 pb-6 text-[11.5px] text-slate-400">
          Illustrative data as of {fmtDate(status.as_of)}. The firm, its clients and people are fictional; listed companies are real.
        </footer>
      )}
    </div>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-7">
      <h1 className="text-[26px] leading-tight font-semibold tracking-tight text-slate-900">{title}</h1>
      {children && <p className="mt-2 max-w-[860px] text-[15px] leading-relaxed text-slate-500">{children}</p>}
    </div>
  );
}
