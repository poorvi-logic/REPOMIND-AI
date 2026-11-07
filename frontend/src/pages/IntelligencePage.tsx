import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { errorText } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import type { ExplanationResponse, FlowNode, Reference } from "../types";
import { Button, Card, CardHeader, ConfidenceBadge, ErrorAlert, Field, LoadingBlock, PageHeader, SourceBadge, cx, inputClass } from "../components/ui";

interface Result {
  loading: boolean;
  error: string | null;
  value: ExplanationResponse | null;
}

const IDLE: Result = { loading: false, error: null, value: null };

function ReferenceLinks({ analysisId, references }: { analysisId: string; references: Reference[] }) {
  if (references.length === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {references.slice(0, 10).map((reference) => (
        <Link
          key={`${reference.file}-${reference.start_line}`}
          to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(reference.file)}&line=${reference.start_line}`}
          className="rounded-md border border-navy-600 px-2.5 py-1 text-xs text-ink-300 hover:border-accent/50 hover:text-ink-100"
        >
          {reference.file}, line {reference.start_line}
        </Link>
      ))}
    </div>
  );
}

function FlowTree({ node, depth }: { node: FlowNode; depth: number }) {
  return (
    <li className="space-y-1">
      <div className="flex items-center gap-2 text-sm" style={{ paddingLeft: depth * 16 }}>
        <span className="font-mono text-ink-200">{node.name}</span>
        {node.confidence && <ConfidenceBadge confidence={node.confidence} />}
        {node.recursive && <span className="text-xs text-ink-500">repeats</span>}
      </div>
      {node.children.length > 0 && <ul className="space-y-1">{node.children.map((child) => <FlowTree key={child.id + child.line} node={child} depth={depth + 1} />)}</ul>}
    </li>
  );
}

function ResultCard({ result, analysisId, flow }: { result: Result; analysisId: string; flow?: FlowNode }) {
  if (result.loading) return <LoadingBlock label="Working" />;
  if (result.error) return <ErrorAlert message={result.error} />;
  if (!result.value) return null;
  return (
    <div className="space-y-4">
      <SourceBadge mode={result.value.mode} status={result.value.ai_status} />
      <p className="whitespace-pre-wrap text-sm leading-7 text-ink-200">{result.value.text}</p>
      {flow && flow.children.length > 0 && <ul className="space-y-1 rounded-lg border border-navy-700 p-4">{flow.children.map((child) => <FlowTree key={child.id + child.line} node={child} depth={0} />)}</ul>}
      <ReferenceLinks analysisId={analysisId} references={result.value.references} />
    </div>
  );
}

export function IntelligencePage() {
  const { analysisId = "" } = useParams();
  const files = useAsync(() => api.files(analysisId), [analysisId]);
  const [filePath, setFilePath] = useState("");
  const [symbolId, setSymbolId] = useState("");
  const [depth, setDepth] = useState(2);
  const [fileResult, setFileResult] = useState<Result>(IDLE);
  const [symbolResult, setSymbolResult] = useState<Result>(IDLE);
  const [projectResult, setProjectResult] = useState<Result>(IDLE);
  const [flowResult, setFlowResult] = useState<Result>(IDLE);
  const [flowTree, setFlowTree] = useState<FlowNode | undefined>(undefined);
  const detail = useAsync(() => api.fileDetail(analysisId, filePath), [analysisId, filePath], Boolean(filePath));

  useEffect(() => { rememberAnalysis(analysisId); }, [analysisId]);
  useEffect(() => {
    if (files.data?.length && !filePath) setFilePath(files.data[0].path);
  }, [files.data, filePath]);
  useEffect(() => {
    setSymbolId("");
    setFileResult(IDLE);
    setSymbolResult(IDLE);
    setFlowResult(IDLE);
    setFlowTree(undefined);
  }, [filePath]);

  const functions = useMemo(() => (detail.data?.symbols ?? []).filter((item) => item.kind !== "nested_function"), [detail.data]);

  async function run(setter: (value: Result) => void, task: () => Promise<ExplanationResponse>) {
    setter({ loading: true, error: null, value: null });
    try {
      setter({ loading: false, error: null, value: await task() });
    } catch (caught) {
      setter({ loading: false, error: errorText(caught), value: null });
    }
  }

  async function traceCalls() {
    setFlowResult({ loading: true, error: null, value: null });
    try {
      const [explanation, flow] = await Promise.all([
        api.explainFlow(analysisId, symbolId, depth),
        api.callFlow(analysisId, symbolId, depth),
      ]);
      setFlowTree(flow.tree);
      setFlowResult({ loading: false, error: null, value: explanation });
    } catch (caught) {
      setFlowResult({ loading: false, error: errorText(caught), value: null });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Code Intelligence" />

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="File" htmlFor="intel-file">
          <select id="intel-file" className={inputClass} value={filePath} onChange={(event) => setFilePath(event.target.value)}>
            {(files.data ?? []).map((file) => <option key={file.path} value={file.path}>{file.path}</option>)}
          </select>
        </Field>
        <Field label="Function" htmlFor="intel-symbol">
          <select id="intel-symbol" className={inputClass} value={symbolId} onChange={(event) => setSymbolId(event.target.value)} disabled={functions.length === 0}>
            <option value="">{functions.length ? "Choose a function" : "No functions in this file"}</option>
            {functions.map((item) => <option key={item.id} value={item.id}>{item.qualname}</option>)}
          </select>
        </Field>
      </div>

      {files.error && <ErrorAlert message={files.error} onRetry={files.reload} />}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="Summarize file" action={<Button variant="secondary" loading={fileResult.loading} disabled={!filePath} onClick={() => void run(setFileResult, () => api.explainFile(analysisId, filePath))}>Run</Button>} />
          <ResultCard result={fileResult} analysisId={analysisId} />
        </Card>

        <Card>
          <CardHeader title="Explain function" action={<Button variant="secondary" loading={symbolResult.loading} disabled={!symbolId} onClick={() => void run(setSymbolResult, () => api.explainSymbol(analysisId, symbolId))}>Run</Button>} />
          <ResultCard result={symbolResult} analysisId={analysisId} />
        </Card>

        <Card>
          <CardHeader title="Explain project" action={<Button variant="secondary" loading={projectResult.loading} onClick={() => void run(setProjectResult, () => api.explainArchitecture(analysisId))}>Run</Button>} />
          <ResultCard result={projectResult} analysisId={analysisId} />
        </Card>

        <Card>
          <CardHeader
            title="Trace calls"
            action={
              <div className="flex items-center gap-2">
                <select aria-label="Depth" className={cx(inputClass, "w-20 py-1.5")} value={depth} onChange={(event) => setDepth(Number(event.target.value))}>
                  {[1, 2, 3, 4].map((value) => <option key={value} value={value}>Depth {value}</option>)}
                </select>
                <Button variant="secondary" loading={flowResult.loading} disabled={!symbolId} onClick={() => void traceCalls()}>Run</Button>
              </div>
            }
          />
          <ResultCard result={flowResult} analysisId={analysisId} flow={flowTree} />
        </Card>
      </div>
    </div>
  );
}
