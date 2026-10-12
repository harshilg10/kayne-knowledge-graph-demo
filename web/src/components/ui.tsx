import clsx from "clsx";
import { AlertTriangle, ChevronDown, Loader2 } from "lucide-react";
import { type ButtonHTMLAttributes, type ReactNode } from "react";
import { ApiError } from "../api";

// ---------------------------------------------------------------- buttons
type ButtonVariant = "primary" | "secondary" | "ghost" | "subtle";

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-brand-600 text-white shadow-sm hover:bg-brand-700",
        variant === "secondary" && "border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        variant === "subtle" && "bg-brand-50 text-brand-700 hover:bg-brand-100",
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- layout bits
export function Badge({ children, color, className }: { children: ReactNode; color?: string; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium whitespace-nowrap",
        !color && "border-slate-200 bg-slate-50 text-slate-600",
        className,
      )}
      style={color ? { borderColor: `${color}55`, background: `${color}14`, color: "#1f2937" } : undefined}
    >
      {color && <span className="size-1.5 rounded-full" style={{ background: color }} />}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- controls
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100/70 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-md font-medium transition-all",
            size === "sm" ? "px-2.5 py-1 text-[12.5px]" : "px-3.5 py-1.5 text-[13px]",
            value === o.value ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Select({
  value,
  onChange,
  children,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("relative", className)}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full appearance-none truncate rounded-lg border border-slate-200 bg-white pr-9 pl-3 text-[13.5px] text-slate-800 shadow-sm outline-none focus:border-brand-400 focus:ring-3 focus:ring-brand-100"
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-slate-400" />
    </div>
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={clsx(
        "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-[13.5px] text-slate-800 shadow-sm outline-none placeholder:text-slate-400 focus:border-brand-400 focus:ring-3 focus:ring-brand-100",
        props.className,
      )}
    />
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2.5 text-[13px] text-slate-700 select-none">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative h-5 w-9 rounded-full transition-colors",
          checked ? "bg-brand-600" : "bg-slate-300",
        )}
      >
        <span
          className={clsx(
            "absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow transition-transform",
            checked && "translate-x-4",
          )}
        />
      </button>
      {label}
    </label>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: ReactNode; count?: number }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-1 border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          onClick={() => onChange(t.value)}
          className={clsx(
            "-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-[13.5px] font-medium transition-colors",
            value === t.value
              ? "border-brand-600 text-brand-700"
              : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          {t.label}
          {t.count != null && (
            <span
              className={clsx(
                "rounded-full px-1.5 text-[11px] tabular-nums",
                value === t.value ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-500",
              )}
            >
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- states
export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} />;
}

export function LoadingBlock({ height = 240, label }: { height?: number; label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white text-[13px] text-slate-500" style={{ height }}>
      <Loader2 className="size-5 animate-spin text-brand-500" />
      {label ?? "Loading…"}
    </div>
  );
}

export function ErrorState({ error, compact = false }: { error: unknown; compact?: boolean }) {
  const message = error instanceof ApiError || error instanceof Error ? error.message : String(error);
  const offline = error instanceof ApiError && error.status === 503;
  return (
    <div className={clsx("rounded-xl border border-amber-200 bg-amber-50 text-amber-900", compact ? "p-3" : "p-5")}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-500" />
        <div className="text-[13.5px] leading-relaxed">
          <div className="font-semibold">{offline ? "The knowledge graph is not available" : "Something went wrong"}</div>
          <div className="mt-1">{message}</div>
          {offline && (
            <pre className="mt-3 rounded-lg bg-white/70 p-3 font-mono text-[12px] text-amber-950">
              scripts/neo4j_start.sh{"\n"}.venv/bin/python -m kgdemo.build
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
