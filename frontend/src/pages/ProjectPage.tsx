import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { Download } from "lucide-react";
import { api } from "../lib/api";
import { formatDate, formatNumber } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import { Button, Card, CardHeader, ErrorAlert, LoadingBlock, PageHeader, SeverityBadge, StatTile } from "../components/ui";

export function ProjectPage() {
  const { analysisId = "" } = useParams();
  const overview = useAsync(() => api.overview(analysisId), [analysisId]);
  const attention = useAsync(() => api.risks(analysisId, { min_severity: "medium" }), [analysisId]);

  useEffect(() => { rememberAnalysis(analysisId); }, [analysisId]);

  async function downloadReport() {
    await api.createReport(analysisId);
    window.location.href = api.reportUrl(analysisId);
  }

  if (overview.loading) return <LoadingBlock label="Loading project" />;
  if (overview.error) return <ErrorAlert message={overview.error} onRetry={overview.reload} />;
  const data = overview.data;
  if (!data) return null;
  const summary = data.summary;
  const coverage = summary.language_coverage;
  const notAnalyzed = Object.entries(coverage?.not_analyzed ?? {});

  return (
    <div className="space-y-7">
      <PageHeader
        title={data.repository}
        actions={<Button variant="secondary" icon={Download} onClick={() => void downloadReport()}>Download report</Button>}
      />
      <p className="-mt-4 text-sm text-ink-400">
        {data.source_type === "github" ? "GitHub" : "ZIP"} · analyzed {formatDate(data.created_at)}
        {data.commit ? ` · commit ${data.commit.slice(0, 8)}` : ""}
      </p>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Python files" value={formatNumber(summary.python_files)} hint={`${formatNumber(summary.total_lines)} lines`} />
        <StatTile label="Functions" value={summary.functions} hint={`${summary.methods} inside classes`} />
        <StatTile label="Classes" value={summary.classes} />
        <StatTile label="Issues to review" value={summary.findings} hint={`${summary.findings_by_severity.high} high`} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Needs attention" />
          {attention.loading && <LoadingBlock />}
          {attention.data && attention.data.findings.length === 0 && <p className="text-sm text-ink-400">Nothing urgent found.</p>}
          <ul className="divide-y divide-navy-700">
            {attention.data?.findings.slice(0, 6).map((finding) => (
              <li key={finding.id} className="flex items-start gap-3 py-3">
                <SeverityBadge severity={finding.severity} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink-100">{finding.title}</p>
                  <Link to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(finding.file)}&line=${finding.line}`} className="text-xs text-ink-400 hover:text-accent">
                    {finding.file}, line {finding.line}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Language coverage" />
            <p className="text-sm text-ink-200">Python: fully analyzed ({formatNumber(coverage?.python_files ?? summary.python_files)} files)</p>
            {notAnalyzed.length > 0 && (
              <>
                <p className="mt-3 text-sm text-ink-400">Not analyzed</p>
                <ul className="mt-1 space-y-1 text-sm text-ink-300">
                  {notAnalyzed.map(([extension, count]) => (
                    <li key={extension} className="flex justify-between"><span className="font-mono">{extension}</span><span className="tabular-nums">{count}</span></li>
                  ))}
                </ul>
              </>
            )}
          </Card>

          <Card>
            <CardHeader title="Most complex functions" />
            {data.most_complex.length === 0 && <p className="text-sm text-ink-400">No functions found.</p>}
            <ul className="space-y-2">
              {data.most_complex.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-3 text-sm">
                  <Link to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(item.file)}&line=${item.line}`} className="truncate font-mono text-ink-200 hover:text-accent">{item.qualname}</Link>
                  <span className="shrink-0 tabular-nums text-ink-400">{item.complexity}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader title="Largest files" />
            <ul className="space-y-2">
              {data.largest_files.map((item) => (
                <li key={item.path} className="flex items-center justify-between gap-3 text-sm">
                  <Link to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(item.path)}`} className="truncate font-mono text-ink-200 hover:text-accent">{item.path}</Link>
                  <span className="shrink-0 tabular-nums text-ink-400">{item.lines} lines</span>
                </li>
              ))}
            </ul>
          </Card>

          {data.dependency_summary.most_called_symbols.length > 0 && (
            <Card>
              <CardHeader title="Most used functions" />
              <ul className="space-y-2">
                {data.dependency_summary.most_called_symbols.slice(0, 5).map((item) => (
                  <li key={item.id} className="flex items-center justify-between text-sm">
                    <span className="truncate font-mono text-ink-200">{item.name}</span>
                    <span className="tabular-nums text-ink-400">{item.confirmed_callers} calls</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {data.cycles.length > 0 && (
            <Card>
              <CardHeader title="Circular imports" />
              <ul className="space-y-2 text-sm">
                {data.cycles.slice(0, 5).map((cycle) => (
                  <li key={cycle.example_cycle.join(">")} className="font-mono text-ink-300">{cycle.example_cycle.join(" → ")}</li>
                ))}
              </ul>
            </Card>
          )}

          {summary.warnings.length > 0 && (
            <Card>
              <CardHeader title="Notes" />
              <ul className="space-y-2 text-sm text-amber-200">
                {summary.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
