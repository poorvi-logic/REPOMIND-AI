import { useState, type DragEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Download, FileArchive, Folder, Link2, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { errorText, formatDate, formatNumber } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import { Button, Card, CardHeader, EmptyState, ErrorAlert, LoadingBlock, PageHeader, cx, inputClass } from "../components/ui";

export function OverviewPage() {
  const navigate = useNavigate();
  const projects = useAsync(() => api.listAnalyses(), []);
  const config = useAsync(() => api.config(), []);
  const [file, setFile] = useState<File | null>(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [busy, setBusy] = useState<"zip" | "github" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function analyze(task: () => Promise<{ analysis_id: string }>, kind: "zip" | "github") {
    setBusy(kind);
    setError(null);
    try {
      const meta = await task();
      rememberAnalysis(meta.analysis_id);
      navigate(`/analyses/${meta.analysis_id}`);
    } catch (caught) {
      setError(errorText(caught));
      setBusy(null);
    }
  }

  function submitArchive(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a ZIP file first.");
      return;
    }
    void analyze(() => api.uploadArchive(file), "zip");
  }

  function submitGithub(event: FormEvent) {
    event.preventDefault();
    if (!githubUrl.trim()) {
      setError("Enter a GitHub repository URL.");
      return;
    }
    void analyze(() => api.analyzeGithub(githubUrl.trim()), "github");
  }

  function dropFile(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }

  async function removeProject(id: string) {
    if (!window.confirm("Delete this project and its analysis?")) return;
    try {
      await api.deleteAnalysis(id);
      projects.reload();
    } catch (caught) {
      setError(errorText(caught));
    }
  }

  async function downloadReport(id: string) {
    try {
      await api.createReport(id);
      window.location.href = api.reportUrl(id);
    } catch (caught) {
      setError(errorText(caught));
    }
  }

  const maxMb = config.data?.limits.max_upload_mb;

  return (
    <div className="space-y-8">
      <PageHeader title="New project" />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <form onSubmit={submitArchive} className="space-y-4">
            <label
              htmlFor="project-zip"
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={dropFile}
              className={cx(
                "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-9 text-center transition",
                dragging ? "border-accent bg-accent/10" : "border-navy-600 hover:border-accent/50",
              )}
            >
              <FileArchive className="h-6 w-6 text-accent" aria-hidden="true" />
              <span className="text-sm text-ink-100">{file ? file.name : "Choose a ZIP file or drop it here"}</span>
              <span className="text-xs text-ink-500">
                {file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : maxMb ? `Up to ${maxMb} MB` : ""}
              </span>
              <input id="project-zip" type="file" accept=".zip,application/zip" className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </label>
            <Button type="submit" loading={busy === "zip"} disabled={!file || busy !== null}>Analyze ZIP</Button>
          </form>
        </Card>

        <Card>
          <form onSubmit={submitGithub} className="space-y-4">
            <div className="relative">
              <Link2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500" aria-hidden="true" />
              <label htmlFor="github-url" className="sr-only">GitHub repository URL</label>
              <input
                id="github-url"
                className={cx(inputClass, "py-2.5 pl-9")}
                placeholder="https://github.com/owner/repository"
                value={githubUrl}
                onChange={(event) => setGithubUrl(event.target.value)}
              />
            </div>
            <Button type="submit" variant="secondary" loading={busy === "github"} disabled={busy !== null}>Clone and analyze</Button>
          </form>
          {error && <div className="mt-4"><ErrorAlert message={error} /></div>}
          {busy && <div className="mt-4"><LoadingBlock label="Analyzing" /></div>}
        </Card>
      </div>

      <section>
        <CardHeader title="Projects" />
        {projects.loading && <LoadingBlock label="Loading projects" />}
        {projects.error && <ErrorAlert message={projects.error} onRetry={projects.reload} />}
        {projects.data && projects.data.length === 0 && <EmptyState icon={Folder} title="No projects yet" />}
        {projects.data && projects.data.length > 0 && (
          <Card className="overflow-hidden p-0">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-navy-700 text-xs text-ink-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Name</th>
                  <th className="px-5 py-3 font-medium">Source</th>
                  <th className="px-5 py-3 text-right font-medium">Python files</th>
                  <th className="px-5 py-3 font-medium">Analyzed</th>
                  <th className="px-5 py-3 text-right font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-700">
                {projects.data.map((item) => (
                  <tr key={item.analysis_id} className="hover:bg-navy-850/60">
                    <td className="px-5 py-3">
                      <button type="button" onClick={() => navigate(`/analyses/${item.analysis_id}`)} className="font-medium text-ink-100 hover:text-accent">
                        {item.repository}
                      </button>
                    </td>
                    <td className="px-5 py-3 text-ink-400">{item.source_type === "github" ? "GitHub" : "ZIP"}</td>
                    <td className="px-5 py-3 text-right tabular-nums text-ink-300">{formatNumber(item.summary.python_files)}</td>
                    <td className="px-5 py-3 text-ink-400">{formatDate(item.created_at)}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1">
                        <button type="button" aria-label="Download report" onClick={() => void downloadReport(item.analysis_id)} className="rounded-md p-1.5 text-ink-400 hover:bg-navy-800 hover:text-ink-100">
                          <Download className="h-4 w-4" />
                        </button>
                        <button type="button" aria-label="Delete project" onClick={() => void removeProject(item.analysis_id)} className="rounded-md p-1.5 text-ink-400 hover:bg-rose-500/10 hover:text-rose-300">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
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
