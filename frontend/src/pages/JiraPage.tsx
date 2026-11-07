import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, ExternalLink, RefreshCw, Send } from "lucide-react";
import { api } from "../lib/api";
import { errorText, formatDate } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { JiraPreview, JiraTicketRecord } from "../types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorAlert, Field, LoadingBlock, PageHeader, inputClass } from "../components/ui";

export function JiraPage() {
  const [searchParams] = useSearchParams();
  const status = useAsync(() => api.jiraStatus(), []);
  const connected = Boolean(status.data?.configured);
  const projects = useAsync(() => api.jiraProjects(), [connected], connected);
  const analyses = useAsync(() => api.listAnalyses(), []);
  const history = useAsync(() => api.jiraTickets(), []);

  const [siteUrl, setSiteUrl] = useState("https://");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const [analysisId, setAnalysisId] = useState(searchParams.get("analysis") ?? "");
  const [findingId, setFindingId] = useState(searchParams.get("finding") ?? "");
  const [projectKey, setProjectKey] = useState("");
  const [issueType, setIssueType] = useState("Task");
  const [preview, setPreview] = useState<JiraPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [created, setCreated] = useState<JiraTicketRecord | null>(null);
  const [issueStatus, setIssueStatus] = useState<string | null>(null);

  const findings = useAsync(() => api.risks(analysisId, { min_severity: "medium" }), [analysisId], Boolean(analysisId));

  useEffect(() => {
    if (!analysisId && analyses.data?.length) setAnalysisId(analyses.data[0].analysis_id);
  }, [analyses.data, analysisId]);

  useEffect(() => {
    if (!findingId && findings.data?.findings.length) setFindingId(findings.data.findings[0].id);
  }, [findings.data, findingId]);

  useEffect(() => {
    const first = projects.data?.[0];
    if (first && !projectKey) {
      setProjectKey(first.key);
      setIssueType(first.issue_types[0] ?? "Task");
    }
  }, [projects.data, projectKey]);

  useEffect(() => {
    setPreview(null);
    setCreated(null);
    setIssueStatus(null);
    setConfirmed(false);
  }, [findingId, projectKey, issueType]);

  const existing = useMemo(
    () => history.data?.find((item) => item.analysis_id === analysisId && item.finding_id === findingId),
    [history.data, analysisId, findingId],
  );
  const selectedProject = projects.data?.find((item) => item.key === projectKey);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setConnecting(true);
    setConnectError(null);
    try {
      await api.jiraConnect({ site_url: siteUrl.trim(), email: email.trim(), api_token: token.trim() });
      setToken("");
      status.reload();
    } catch (caught) {
      setConnectError(errorText(caught));
    } finally {
      setConnecting(false);
    }
  }

  async function disconnect() {
    await api.jiraDisconnect();
    status.reload();
  }

  async function runPreview() {
    setPreviewing(true);
    setActionError(null);
    try {
      setPreview(await api.jiraPreview({ analysis_id: analysisId, finding_id: findingId, project_key: projectKey, issue_type: issueType }));
    } catch (caught) {
      setActionError(errorText(caught));
    } finally {
      setPreviewing(false);
    }
  }

  async function createIssue() {
    setCreating(true);
    setActionError(null);
    try {
      const record = await api.jiraCreate({ analysis_id: analysisId, finding_id: findingId, project_key: projectKey, issue_type: issueType });
      setCreated(record);
      history.reload();
    } catch (caught) {
      setActionError(errorText(caught));
    } finally {
      setCreating(false);
    }
  }

  async function refreshStatus() {
    if (!created) return;
    try {
      const current = await api.jiraIssueStatus(created.issue_key);
      setIssueStatus([current.status, current.assignee].filter(Boolean).join(" · ") || "No status");
    } catch (caught) {
      setIssueStatus(errorText(caught));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Jira" />

      <Card>
        <CardHeader
          title="Connection"
          action={connected ? <Badge tone="emerald">Connected</Badge> : <Badge>Not connected</Badge>}
        />
        {status.loading && <LoadingBlock />}
        {connected && (
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-300">
            <span>{status.data?.base_url} · {status.data?.email}</span>
            {status.data?.session_override_active && <Button variant="danger" onClick={() => void disconnect()}>Disconnect</Button>}
          </div>
        )}
        {!connected && !status.loading && (
          <form onSubmit={connect} className="grid gap-4 md:grid-cols-3">
            <Field label="Site" htmlFor="jira-site">
              <input id="jira-site" className={inputClass} value={siteUrl} onChange={(event) => setSiteUrl(event.target.value)} />
            </Field>
            <Field label="Email" htmlFor="jira-email">
              <input id="jira-email" type="email" className={inputClass} value={email} onChange={(event) => setEmail(event.target.value)} />
            </Field>
            <Field label="API token" htmlFor="jira-token">
              <input id="jira-token" type="password" autoComplete="off" className={inputClass} value={token} onChange={(event) => setToken(event.target.value)} />
            </Field>
            <div className="md:col-span-3">
              <Button type="submit" loading={connecting} disabled={!email || token.length < 8}>Connect</Button>
            </div>
          </form>
        )}
        {connectError && <div className="mt-4"><ErrorAlert message={connectError} /></div>}
      </Card>

      {connected && (
        <Card>
          <CardHeader title="Create issue" />
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Project" htmlFor="jira-analysis">
              <select id="jira-analysis" className={inputClass} value={analysisId} onChange={(event) => { setAnalysisId(event.target.value); setFindingId(""); }}>
                {(analyses.data ?? []).map((item) => <option key={item.analysis_id} value={item.analysis_id}>{item.repository}</option>)}
              </select>
            </Field>
            <Field label="Issue" htmlFor="jira-finding">
              <select id="jira-finding" className={inputClass} value={findingId} onChange={(event) => setFindingId(event.target.value)}>
                {(findings.data?.findings ?? []).map((finding) => (
                  <option key={finding.id} value={finding.id}>{finding.title} · {finding.file}:{finding.line}</option>
                ))}
              </select>
            </Field>
            <Field label="Jira project" htmlFor="jira-project">
              {projects.loading ? <LoadingBlock /> : (
                <select id="jira-project" className={inputClass} value={projectKey} onChange={(event) => { setProjectKey(event.target.value); setIssueType(projects.data?.find((item) => item.key === event.target.value)?.issue_types[0] ?? "Task"); }}>
                  {(projects.data ?? []).map((item) => <option key={item.key} value={item.key}>{item.key} · {item.name}</option>)}
                </select>
              )}
            </Field>
            <Field label="Type" htmlFor="jira-type">
              <select id="jira-type" className={inputClass} value={issueType} onChange={(event) => setIssueType(event.target.value)}>
                {(selectedProject?.issue_types.length ? selectedProject.issue_types : ["Task"]).map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </Field>
          </div>

          {projects.error && <div className="mt-4"><ErrorAlert message={projects.error} onRetry={projects.reload} /></div>}
          {actionError && <div className="mt-4"><ErrorAlert message={actionError} /></div>}

          {existing && (
            <p className="mt-5 flex items-center gap-2 text-sm text-emerald-300">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Already created as {existing.issue_key}
            </p>
          )}

          {!existing && (
            <div className="mt-5 flex flex-wrap gap-3">
              <Button variant="secondary" loading={previewing} disabled={!findingId || !projectKey} onClick={() => void runPreview()}>Preview</Button>
            </div>
          )}

          {preview && !existing && !created && (
            <div className="mt-6 space-y-4 rounded-lg border border-navy-700 p-5">
              <p className="font-medium text-ink-50">{preview.summary}</p>
              <div className="flex flex-wrap gap-1.5">
                {preview.labels.map((label) => <Badge key={label}>{label}</Badge>)}
              </div>
              {preview.warnings.map((warning) => <p key={warning} className="text-sm text-amber-200">{warning}</p>)}
              <div className="space-y-2 text-sm leading-6 text-ink-300">
                {preview.description.split("\n").filter(Boolean).map((line, index) => <p key={index}>{line}</p>)}
              </div>
              <label className="flex cursor-pointer items-center gap-2.5 text-sm text-ink-300">
                <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="h-4 w-4 accent-[#8c9bff]" />
                Create this issue in Jira
              </label>
              <Button icon={Send} loading={creating} disabled={!confirmed} onClick={() => void createIssue()}>Create issue</Button>
            </div>
          )}

          {created && (
            <div className="mt-6 space-y-3 rounded-lg border border-emerald-400/25 bg-emerald-500/5 p-5">
              <p className="flex items-center gap-2 font-medium text-emerald-200">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                Created {created.issue_key}
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <a href={created.issue_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
                  Open in Jira <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
                <Button variant="ghost" icon={RefreshCw} onClick={() => void refreshStatus()}>Check status</Button>
                {issueStatus && <span className="text-sm text-ink-300">{issueStatus}</span>}
              </div>
            </div>
          )}
        </Card>
      )}

      <section>
        <CardHeader title="Created issues" />
        {history.loading && <LoadingBlock />}
        {history.data && history.data.length === 0 && <EmptyState icon={CheckCircle2} title="No issues created yet" />}
        {history.data && history.data.length > 0 && (
          <Card className="overflow-hidden p-0">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-navy-700 text-xs text-ink-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Issue</th>
                  <th className="px-5 py-3 font-medium">Project</th>
                  <th className="px-5 py-3 font-medium">Title</th>
                  <th className="px-5 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-700">
                {history.data.map((ticket) => (
                  <tr key={ticket.id}>
                    <td className="px-5 py-3"><a href={ticket.issue_url} target="_blank" rel="noreferrer" className="font-mono text-accent hover:underline">{ticket.issue_key}</a></td>
                    <td className="px-5 py-3 text-ink-300">{ticket.project_key}</td>
                    <td className="max-w-md truncate px-5 py-3 text-ink-300" title={ticket.summary}>{ticket.summary}</td>
                    <td className="px-5 py-3 text-ink-500">{formatDate(ticket.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}
