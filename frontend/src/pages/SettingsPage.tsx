import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { errorText } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { Preferences, Severity } from "../types";
import { Badge, Button, Card, CardHeader, ErrorAlert, Field, LoadingBlock, PageHeader, inputClass } from "../components/ui";

const SOURCE_LABEL: Record<string, string> = {
  session: "Key entered in this session",
  environment: "Key set on the server",
};

export function SettingsPage() {
  const config = useAsync(() => api.config(), []);
  const ai = useAsync(() => api.aiStatus(), []);
  const preferences = useAsync(() => api.preferences(), []);
  const [key, setKey] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [form, setForm] = useState<Preferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (preferences.data) setForm(preferences.data);
  }, [preferences.data]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setAiBusy(true);
    setAiError(null);
    try {
      const status = await api.aiConnect(key.trim());
      ai.setData(status);
      setKey("");
    } catch (caught) {
      setAiError(errorText(caught));
    } finally {
      setAiBusy(false);
    }
  }

  async function disconnect() {
    setAiBusy(true);
    try {
      ai.setData(await api.aiDisconnect());
    } catch (caught) {
      setAiError(errorText(caught));
    } finally {
      setAiBusy(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      preferences.setData(await api.savePreferences(form));
      setSaved(true);
    } catch (caught) {
      setSaveError(errorText(caught));
    } finally {
      setSaving(false);
    }
  }

  const aiConnected = Boolean(ai.data?.connected);
  const limits = config.data?.limits;

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="AI" action={aiConnected ? <Badge tone="emerald">Connected</Badge> : <Badge>Not connected</Badge>} />
          {ai.loading && <LoadingBlock />}
          {ai.data && (
            <dl className="mb-5 grid grid-cols-[110px_1fr] gap-y-2 text-sm">
              <dt className="text-ink-500">Model</dt>
              <dd className="font-mono text-ink-200">{ai.data.model}</dd>
              <dt className="text-ink-500">Key</dt>
              <dd className="text-ink-200">{aiConnected && ai.data.source ? SOURCE_LABEL[ai.data.source] : "None"}</dd>
            </dl>
          )}
          {ai.data?.source !== "environment" && (
            <form onSubmit={connect} className="space-y-3">
              <Field label={aiConnected ? "Replace key" : "OpenAI API key"} htmlFor="ai-key">
                <input id="ai-key" type="password" autoComplete="off" className={inputClass} value={key} onChange={(event) => setKey(event.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button type="submit" loading={aiBusy} disabled={key.trim().length < 20}>Connect</Button>
                {aiConnected && ai.data?.source === "session" && <Button variant="danger" onClick={() => void disconnect()} disabled={aiBusy}>Remove</Button>}
              </div>
            </form>
          )}
          {aiError && <div className="mt-4"><ErrorAlert message={aiError} /></div>}
        </Card>

        <Card>
          <CardHeader title="Analysis" />
          {preferences.loading && <LoadingBlock />}
          {form && (
            <form onSubmit={save} className="space-y-4">
              <Field label="Search method" htmlFor="pref-retrieval">
                <select id="pref-retrieval" className={inputClass} value={form.retrieval_mode} onChange={(event) => setForm({ ...form, retrieval_mode: event.target.value as Preferences["retrieval_mode"] })}>
                  <option value="lexical">Keyword search</option>
                  <option value="hybrid" disabled={!aiConnected}>Keyword and AI search{aiConnected ? "" : " (connect AI first)"}</option>
                </select>
              </Field>
              <Field label="Show issues from" htmlFor="pref-severity">
                <select id="pref-severity" className={inputClass} value={form.default_risk_severity} onChange={(event) => setForm({ ...form, default_risk_severity: event.target.value as Severity })}>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                  <option value="info">Info</option>
                </select>
              </Field>
              <div className="flex items-center gap-3">
                <Button type="submit" loading={saving}>Save</Button>
                {saved && <span className="text-sm text-emerald-300">Saved</span>}
              </div>
              {saveError && <ErrorAlert message={saveError} />}
            </form>
          )}
        </Card>

        <Card>
          <CardHeader title="Limits" />
          {config.loading && <LoadingBlock />}
          {limits && (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <dt className="text-ink-500">Largest upload</dt><dd className="text-ink-200">{limits.max_upload_mb} MB</dd>
              <dt className="text-ink-500">Largest project</dt><dd className="text-ink-200">{limits.max_repository_mb} MB of Python</dd>
              <dt className="text-ink-500">Python files</dt><dd className="text-ink-200">{limits.max_python_files.toLocaleString()}</dd>
              <dt className="text-ink-500">Largest file</dt><dd className="text-ink-200">{limits.max_file_kb} KB</dd>
              <dt className="text-ink-500">Clone timeout</dt><dd className="text-ink-200">{limits.clone_timeout_seconds} s</dd>
            </dl>
          )}
        </Card>

        <Card>
          <CardHeader title="Jira" action={config.data?.jira.configured ? <Badge tone="emerald">Connected</Badge> : <Badge>Not connected</Badge>} />
          <p className="text-sm text-ink-400">
            {config.data?.jira.configured ? config.data.jira.base_url : "Connect a Jira site to create issues from findings."}
          </p>
          <Link to="/jira" className="mt-4 inline-block text-sm text-accent hover:underline">Open Jira</Link>
        </Card>
      </div>
    </div>
  );
}
