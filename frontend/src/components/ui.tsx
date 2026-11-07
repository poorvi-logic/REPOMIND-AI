import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Confidence, Severity } from "../types";
import { AI_ERROR_NOTE, CONFIDENCE_BADGE, CONFIDENCE_LABEL, SEVERITY_BADGE, SEVERITY_LABEL, sourceLabel } from "../lib/format";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({ children, className, id }: { children: ReactNode; className?: string; id?: string }) {
  return (
    <section id={id} className={cx("rounded-xl border border-navy-700 bg-navy-850/80 p-5", className)}>
      {children}
    </section>
  );
}

export function CardHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-ink-100">{title}</h2>
      {action}
    </div>
  );
}

export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
      <h1 className="text-xl font-semibold tracking-tight text-ink-50">{title}</h1>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

type Tone = "neutral" | "emerald" | "amber" | "rose" | "sky" | "violet" | "accent";
const TONES: Record<Tone, string> = {
  neutral: "bg-navy-700 text-ink-200 ring-navy-600",
  emerald: "bg-emerald-500/15 text-emerald-200 ring-emerald-400/30",
  amber: "bg-amber-500/15 text-amber-200 ring-amber-400/30",
  rose: "bg-rose-500/15 text-rose-200 ring-rose-400/30",
  sky: "bg-sky-500/15 text-sky-200 ring-sky-400/30",
  violet: "bg-violet-500/15 text-violet-200 ring-violet-400/30",
  accent: "bg-accent/15 text-accent ring-accent/30",
};

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={cx("inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", SEVERITY_BADGE[severity])}>{SEVERITY_LABEL[severity]}</span>;
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence | string }) {
  return (
    <span className={cx("inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", CONFIDENCE_BADGE[confidence] ?? TONES.neutral)}>
      {CONFIDENCE_LABEL[confidence] ?? confidence}
    </span>
  );
}

export function SourceBadge({ mode, status }: { mode: string; status: string }) {
  const note = AI_ERROR_NOTE[status];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={mode === "llm" ? "violet" : mode === "insufficient-evidence" ? "amber" : "sky"}>{sourceLabel(mode)}</Badge>
      {note && <span className="text-xs text-ink-400">{note}</span>}
    </div>
  );
}

export function StatTile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border border-navy-700 bg-navy-850/80 px-4 py-3.5">
      <div className="text-xs text-ink-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink-50">{typeof value === "number" ? value.toLocaleString() : value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-ink-500">{hint}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-4 w-4 animate-spin text-accent", className)} aria-hidden="true" />;
}

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 rounded-lg border border-navy-700 bg-navy-900/60 px-4 py-4 text-sm text-ink-300">
      <Spinner />
      {label}
    </div>
  );
}

export function ErrorAlert({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-start gap-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" aria-hidden="true" />
      <p className="min-w-0 flex-1 leading-6">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="rounded-md border border-rose-300/30 px-2.5 py-1 text-xs font-medium text-rose-100 hover:bg-rose-400/10">
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, action }: { icon: LucideIcon; title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-navy-700 px-6 py-10 text-center">
      <Icon className="h-6 w-6 text-ink-500" aria-hidden="true" />
      <p className="text-sm text-ink-400">{title}</p>
      {action}
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-navy-950 hover:bg-accent-strong hover:text-white",
  secondary: "border border-navy-600 bg-navy-800 text-ink-100 hover:border-accent/50 hover:bg-navy-700",
  ghost: "text-ink-300 hover:bg-navy-800 hover:text-ink-100",
  danger: "border border-rose-400/30 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20",
};

export function Button({
  variant = "primary", loading = false, icon: Icon, children, className, disabled, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean; icon?: LucideIcon }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-50",
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner className="text-current" /> : Icon ? <Icon className="h-4 w-4" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

export function Field({ label, children, htmlFor }: { label: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-400">{label}</label>
      {children}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-navy-600 bg-navy-950/70 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20";
