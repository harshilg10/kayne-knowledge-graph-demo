import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import { DOC_TYPE_COLORS } from "../lib/colors";
import { fmtDate } from "../lib/format";
import type { DocDetail } from "../types";
import { Badge, ErrorState, LoadingBlock } from "./ui";

// ---------------------------------------------------------------- formatted document
interface HeaderField {
  key: string;
  values: string[];
}

function parseHeader(header: string): { title: string; fields: HeaderField[] } {
  const lines = header.split("\n");
  const title = (lines.shift() ?? "").trim();
  const fields: HeaderField[] = [];
  let current: HeaderField | null = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      current = null;
      continue;
    }
    const m = /^([A-Z][A-Za-z ]{1,30}):\s*(.*)$/.exec(line);
    if (m) {
      current = { key: m[1], values: m[2] ? [m[2]] : [] };
      fields.push(current);
    } else if (current) {
      current.values.push(line);
    }
  }
  return { title, fields };
}

function FormattedBody({ text }: { text: string }) {
  const blocks = text.trim().split(/\n\s*\n/);
  return (
    <div className="space-y-3 text-[14px] leading-relaxed text-slate-700">
      {blocks.map((block, i) => {
        const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
        return (
          <div key={i} className="space-y-1.5">
            {lines.map((line, j) => {
              if (line.endsWith(":") && line.length <= 60 && !line.startsWith("- "))
                return <div key={j} className="pt-1 text-[12px] font-semibold tracking-wide text-slate-900 uppercase">{line.slice(0, -1)}</div>;
              if (line.startsWith("- "))
                return (
                  <div key={j} className="flex gap-2 pl-1">
                    <span className="mt-[9px] size-1 shrink-0 rounded-full bg-slate-400" />
                    <span>{line.slice(2)}</span>
                  </div>
                );
              return <p key={j}>{line}</p>;
            })}
          </div>
        );
      })}
    </div>
  );
}

export function DocumentView({ doc }: { doc: DocDetail }) {
  const { title, fields } = useMemo(() => parseHeader(doc.text.slice(0, doc.body_offset)), [doc]);
  const body = doc.text.slice(doc.body_offset);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge color={DOC_TYPE_COLORS[doc.doc_type]}>{doc.doc_type}</Badge>
        <span className="font-mono text-[11.5px] text-slate-400">{doc.doc_id}</span>
      </div>
      <h2 className="mt-2 text-[19px] leading-snug font-semibold tracking-tight text-slate-900">{title || doc.title}</h2>
      {fields.length > 0 && (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-lg border border-slate-100 bg-slate-50/70 px-4 py-3 text-[13px]">
          {fields.map((f) => (
            <div key={f.key} className="contents">
              <dt className="text-slate-500">{f.key}</dt>
              <dd className="text-slate-800">{f.key === "Date" || f.key === "Published" ? fmtDate(f.values.join(", ")) : f.values.join(", ")}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-5">
        <FormattedBody text={body} />
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-3 text-[12px] text-slate-500">
        <span>Source system: {doc.source_system}</span>
        <span className="text-slate-300">•</span>
        <span className="font-mono text-[11.5px]">{doc.source_path}</span>
      </div>
    </div>
  );
}

export function DownloadOriginal({ doc }: { doc: { doc_id: string; file_ext: string; file_name: string } }) {
  if (!doc.file_ext) return null;
  return (
    <a
      href={`/api/documents/${encodeURIComponent(doc.doc_id)}/original`}
      download={doc.file_name}
      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-[12.5px] font-medium text-slate-700 shadow-sm hover:bg-slate-50"
    >
      <Download className="size-3.5" /> Original .{doc.file_ext}
    </a>
  );
}

// ---------------------------------------------------------------- drawer
const DrawerContext = createContext<{ open: (docId: string) => void }>({ open: () => undefined });

export function useDocDrawer() {
  return useContext(DrawerContext);
}

export function DocumentDrawerProvider({ children }: { children: ReactNode }) {
  const [docId, setDocId] = useState<string | null>(null);
  const open = useCallback((id: string) => setDocId(id), []);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <DrawerContext.Provider value={value}>
      {children}
      {docId && <Drawer docId={docId} onClose={() => setDocId(null)} />}
    </DrawerContext.Provider>
  );
}

function Drawer({ docId, onClose }: { docId: string; onClose: () => void }) {
  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.get<DocDetail>(`/api/documents/${encodeURIComponent(docId)}`) });
  const [shown, setShown] = useState(false);
  useEffect(() => {
    requestAnimationFrame(() => setShown(true));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50">
      <div className={clsx("absolute inset-0 bg-ink-950/25 transition-opacity", shown ? "opacity-100" : "opacity-0")} onClick={onClose} />
      <aside
        role="dialog"
        aria-label="Document"
        className={clsx(
          "absolute top-0 right-0 flex h-full w-full max-w-[680px] flex-col bg-white shadow-2xl transition-transform duration-200",
          shown ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex items-center justify-end gap-2 px-5 pt-4">
          {doc.data && <DownloadOriginal doc={doc.data} />}
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto px-8 pt-2 pb-8">
          {doc.isLoading && <LoadingBlock height={300} />}
          {doc.error && <ErrorState error={doc.error} />}
          {doc.data && <DocumentView doc={doc.data} />}
        </div>
      </aside>
    </div>
  );
}
