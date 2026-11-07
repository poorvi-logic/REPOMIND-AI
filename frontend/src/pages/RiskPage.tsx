import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { errorText, SEVERITY_ORDER } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import type { ExplanationResponse, Finding, Severity } from "../types";
import { Button, ErrorAlert, Field, LoadingBlock, PageHeader, SeverityBadge, SourceBadge, cx, inputClass } from "../components/ui";

interface Group {
  ruleId: string;
  title: string;
  severity: Severity;
  items: Finding[];
}

function groupFindings(findings: Finding[]): Group[] {
  const groups = new Map<string, Group>();
  for (const finding of findings) {
    const existing = groups.get(finding.rule_id);
    if (existing) {
      existing.items.push(finding);
      if (SEVERITY_ORDER.indexOf(finding.severity) < SEVERITY_ORDER.indexOf(existing.severity)) existing.severity = finding.severity;
    } else {
      groups.set(finding.rule_id, { ruleId: finding.rule_id, title: finding.title, severity: finding.severity, items: [finding] });
    }
  }
  return [...groups.values()].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) || b.items.length - a.items.length);
}

export function RiskPage() {
  const { analysisId = "" } = useParams();
  const navigate = useNavigate();
  const [minSeverity, setMinSeverity] = useState<Severity>("medium");
  const [text, setText] = useState("");
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const [explanations, setExplanations] = useState<Record<string, { loading: boolean; error?: string; value?: ExplanationResponse }>>({});
  const risks = useAsync(() => api.risks(analysisId, { min_severity: minSeverity }), [analysisId, minSeverity]);

  useEffect(() => { rememberAnalysis(analysisId); }, [analysisId]);

  const groups = useMemo(() => {
    const needle = text.trim().toLowerCase();
    const matching = (risks.data?.findings ?? []).filter((finding) =>
      !needle || [finding.title, finding.file, finding.rule_id].some((value) => value.toLowerCase().includes(needle)),
    );
    return groupFindings(matching);
  }, [risks.data, text]);

  function toggleGroup(ruleId: string) {
    setOpenGroups((current) => {
      const next = new Set(current);
      if (next.has(ruleId)) next.delete(ruleId); else next.add(ruleId);
      return next;
    });
  }

  async function explain(finding: Finding) {
    setExplanations((current) => ({ ...current, [finding.id]: { loading: true } }));
    try {
      const value = await api.explainFinding(analysisId, finding.id);
      setExplanations((current) => ({ ...current, [finding.id]: { loading: false, value } }));
    } catch (caught) {
      setExplanations((current) => ({ ...current, [finding.id]: { loading: false, error: errorText(caught) } }));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Risk Analysis" />

      <div className="flex flex-wrap items-end gap-4">
        <div className="w-56">
          <Field label="Show" htmlFor="risk-severity">
            <select id="risk-severity" className={inputClass} value={minSeverity} onChange={(event) => setMinSeverity(event.target.value as Severity)}>
              <option value="medium">Medium and high</option>
              <option value="low">Low and above</option>
              <option value="info">Everything</option>
            </select>
          </Field>
        </div>
        <div className="w-72">
          <Field label="Search" htmlFor="risk-text">
            <input id="risk-text" className={inputClass} value={text} onChange={(event) => setText(event.target.value)} placeholder="File or issue" />
          </Field>
        </div>
        <p className="pb-2 text-sm text-ink-400">{risks.data?.total ?? 0} issues in {groups.length} groups</p>
      </div>

      {risks.loading && <LoadingBlock label="Loading issues" />}
      {risks.error && <ErrorAlert message={risks.error} onRetry={risks.reload} />}
      {risks.data && risks.data.total === 0 && <p className="text-sm text-ink-400">No issues found by the checks that ran.</p>}

      <div className="space-y-3">
        {groups.map((group) => {
          const open = openGroups.has(group.ruleId);
          return (
            <section key={group.ruleId} className="overflow-hidden rounded-xl border border-navy-700 bg-navy-850/80">
              <button type="button" onClick={() => toggleGroup(group.ruleId)} className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-navy-800/60">
                {open ? <ChevronDown className="h-4 w-4 text-ink-500" aria-hidden="true" /> : <ChevronRight className="h-4 w-4 text-ink-500" aria-hidden="true" />}
                <SeverityBadge severity={group.severity} />
                <span className="flex-1 text-sm font-medium text-ink-100">{group.title}</span>
                <span className="tabular-nums text-sm text-ink-400">{group.items.length}</span>
              </button>
              {open && (
                <ul className="divide-y divide-navy-700 border-t border-navy-700">
                  {group.items.map((finding) => {
                    const state = explanations[finding.id];
                    return (
                      <li key={finding.id} className={cx("space-y-3 px-5 py-4 pl-12")}>
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <Link to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(finding.file)}&line=${finding.line}`} className="font-mono text-sm text-ink-200 hover:text-accent">
                            {finding.file}, line {finding.line}
                          </Link>
                          <div className="flex gap-2">
                            <Button variant="ghost" loading={state?.loading} onClick={() => void explain(finding)}>Explain</Button>
                            {(finding.severity === "high" || finding.severity === "medium") && (
                              <Button variant="secondary" onClick={() => navigate(`/jira?analysis=${analysisId}&finding=${encodeURIComponent(finding.id)}`)}>Create Jira issue</Button>
                            )}
                          </div>
                        </div>
                        {finding.why_it_matters && <p className="text-sm text-ink-400">{finding.why_it_matters}</p>}
                        <p className="text-sm text-ink-300">{finding.remediation}</p>
                        {state?.error && <ErrorAlert message={state.error} />}
                        {state?.value && (
                          <div className="space-y-2 rounded-lg border border-navy-700 p-4">
                            <SourceBadge mode={state.value.mode} status={state.value.ai_status} />
                            <p className="whitespace-pre-wrap text-sm leading-6 text-ink-200">{state.value.text}</p>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
