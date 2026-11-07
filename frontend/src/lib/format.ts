import type { Severity } from "../types";

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low", "info"];

export const SEVERITY_LABEL: Record<Severity, string> = { high: "High", medium: "Medium", low: "Low", info: "Info" };

export const SEVERITY_BADGE: Record<Severity, string> = {
  high: "bg-rose-500/15 text-rose-300 ring-rose-400/30",
  medium: "bg-amber-500/15 text-amber-200 ring-amber-400/30",
  low: "bg-sky-500/15 text-sky-200 ring-sky-400/30",
  info: "bg-slate-500/20 text-slate-300 ring-slate-400/30",
};

export const SEVERITY_BAR: Record<Severity, string> = {
  high: "border-l-rose-400",
  medium: "border-l-amber-400",
  low: "border-l-sky-400",
  info: "border-l-slate-500",
};

export const SEVERITY_HEX: Record<Severity, string> = { high: "#fb7185", medium: "#fbbf24", low: "#38bdf8", info: "#94a3b8" };

export const CONFIDENCE_LABEL: Record<string, string> = {
  confirmed: "Exact",
  approximate: "Name match",
  external: "Library",
  unresolved: "Unknown",
  heuristic: "Suggestion",
};

export const CONFIDENCE_BADGE: Record<string, string> = {
  confirmed: "bg-emerald-500/15 text-emerald-200 ring-emerald-400/30",
  approximate: "bg-amber-500/15 text-amber-200 ring-amber-400/30",
  external: "bg-slate-500/20 text-slate-300 ring-slate-400/30",
  unresolved: "bg-rose-500/10 text-rose-200 ring-rose-400/25",
  heuristic: "bg-violet-500/15 text-violet-200 ring-violet-400/30",
};

export const AI_ERROR_NOTE: Record<string, string> = {
  rate_limited: "AI is rate limited right now.",
  timeout: "AI timed out.",
  auth_error: "The AI key was rejected.",
  api_error: "AI is unavailable right now.",
  empty_response: "AI returned an empty reply.",
};

export function sourceLabel(mode: string): string {
  if (mode === "llm") return "Written by AI";
  if (mode === "insufficient-evidence") return "Not found in project";
  return "From code analysis";
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
