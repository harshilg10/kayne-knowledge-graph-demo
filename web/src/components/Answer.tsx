import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import { useDocDrawer } from "./DocumentDrawer";

const ID = String.raw`(?:DOC-[A-Z]+-\d+|DOC-LIVE-[0-9A-F]+|IC-\d{4}-\d{3}|TXN-\d{6}|MTG-[A-Z0-9-]+|C-\d{3}|ACC-\d{4})`;
const BRACKET = new RegExp(String.raw`\[(${ID}(?:\s*[,;]\s*${ID})*)\]`, "g");

/** "[DOC-EM-08, IC-2026-004]" -> markdown links with the custom "cite:" scheme, rendered as chips. */
function linkCitations(text: string): string {
  return text.replace(BRACKET, (_m, inner: string) =>
    inner
      .split(/\s*[,;]\s*/)
      .map((id) => `[${id}](cite:${id})`)
      .join(" "),
  );
}

export function Answer({ text }: { text: string }) {
  const { open } = useDocDrawer();
  return (
    <div className="prose-answer">
      <ReactMarkdown
        urlTransform={(url) => (url.startsWith("cite:") ? url : defaultUrlTransform(url))}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("cite:")) {
              const id = href.slice(5);
              const isDoc = id.startsWith("DOC-");
              return isDoc ? (
                <button
                  type="button"
                  onClick={() => open(id)}
                  title="Open the source document"
                  className="mx-0.5 inline-flex translate-y-[-1px] items-center rounded-md border border-brand-200 bg-brand-50 px-1.5 font-mono text-[11px] leading-[18px] text-brand-700 hover:bg-brand-100"
                >
                  {id}
                </button>
              ) : (
                <span className="mx-0.5 inline-flex translate-y-[-1px] items-center rounded-md border border-slate-200 bg-slate-50 px-1.5 font-mono text-[11px] leading-[18px] text-slate-600">
                  {children}
                </span>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-brand-700 underline">
                {children}
              </a>
            );
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
}
