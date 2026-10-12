import clsx from "clsx";
import { Check, Copy } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";

const KEYWORDS = new Set(
  (
    "MATCH OPTIONAL WHERE RETURN WITH UNWIND AS AND OR NOT IN IS NULL ORDER BY DESC ASC LIMIT SKIP DISTINCT " +
    "CALL YIELD UNION ALL EXISTS COUNT CASE WHEN THEN ELSE END MERGE CREATE SET DELETE DETACH ON STARTS ENDS CONTAINS"
  ).split(" "),
);
const FUNCTIONS = new Set(
  (
    "count sum collect coalesce toString round date duration labels type elementId size any all none head tail " +
    "toLower toUpper split nodes relationships"
  ).split(" "),
);

// tokens: comments, strings, parameters, labels/rel types after ':', numbers, words, everything else
const TOKEN = /(\/\/[^\n]*)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\$[A-Za-z_]\w*)|(:[A-Z][A-Za-z_]*)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)|([\s\S])/g;

function highlightCypher(code: string): ReactNode[] {
  const out: ReactNode[] = [];
  let m: RegExpExecArray | null;
  let i = 0;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(code))) {
    const [text, comment, str, param, label, num, word] = m;
    let cls = "";
    if (comment) cls = "text-slate-400 italic";
    else if (str) cls = "text-emerald-600";
    else if (param) cls = "text-fuchsia-600";
    else if (label) cls = "text-amber-700";
    else if (num) cls = "text-sky-700";
    else if (word && KEYWORDS.has(word.toUpperCase()) && word === word.toUpperCase()) cls = "font-semibold text-brand-700";
    else if (word && FUNCTIONS.has(word)) cls = "text-sky-700";
    out.push(cls ? <span key={i++} className={cls}>{text}</span> : <Fragment key={i++}>{text}</Fragment>);
  }
  return out;
}

export function CodeBlock({ code, title, maxHeight = 360, className }: { code: string; title?: string; maxHeight?: number; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className={clsx("overflow-hidden rounded-lg border border-slate-200 bg-slate-50/70", className)}>
      <div className="flex items-center justify-between border-b border-slate-200 bg-white/60 px-3 py-1.5">
        <span className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">{title ?? "Cypher"}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="scrollbar-thin overflow-auto p-3 font-mono text-[12px] leading-[1.6] text-slate-700" style={{ maxHeight }}>
        <code>{highlightCypher(code)}</code>
      </pre>
    </div>
  );
}
