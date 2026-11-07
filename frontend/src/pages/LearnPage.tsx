import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import dagre from "dagre";
import { api } from "../lib/api";
import { errorText } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import type { LearningAnswer, LearningBatch, LearningProgress, LearningQuestion } from "../types";
import { Badge, Button, Card, CardHeader, ErrorAlert, Field, LoadingBlock, PageHeader, cx, inputClass } from "../components/ui";
import { CodeView } from "../components/CodeView";

const DIFFICULTY_TONE: Record<string, "emerald" | "amber" | "rose"> = { beginner: "emerald", intermediate: "amber", advanced: "rose" };

interface DiagramNode extends Record<string, unknown> {
  label: string;
  highlighted: boolean;
  dimmed: boolean;
}

function DiagramCard({ data }: NodeProps<Node<DiagramNode>>) {
  return (
    <div className={cx("flex h-full items-center justify-center rounded-lg border px-3 text-center text-xs", data.highlighted ? "border-accent bg-accent/10 text-ink-50" : "border-navy-600 bg-navy-850 text-ink-300", data.dimmed && "opacity-40")}>
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-navy-600" />
      <span className="truncate font-mono">{data.label}</span>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-navy-600" />
    </div>
  );
}

const diagramTypes = { card: DiagramCard };

function ModuleDiagram({ analysisId, highlight }: { analysisId: string; highlight: string[] }) {
  const graph = useAsync(() => api.dependencies(analysisId, { scope: "modules", confidence: "confirmed", max_nodes: 14 }), [analysisId]);
  const laid = useMemo(() => {
    if (!graph.data) return null;
    const focus = new Set(highlight);
    const neighbours = new Set<string>(focus);
    graph.data.edges.forEach((edge) => {
      if (focus.has(edge.source) || focus.has(edge.target)) {
        neighbours.add(edge.source);
        neighbours.add(edge.target);
      }
    });
    const nodes = graph.data.nodes.filter((node) => neighbours.size === 0 || neighbours.has(node.id));
    const ids = new Set(nodes.map((node) => node.id));
    const edges = graph.data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    const layout = new dagre.graphlib.Graph();
    layout.setGraph({ rankdir: "TB", nodesep: 22, ranksep: 46, marginx: 16, marginy: 16 });
    layout.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((node) => layout.setNode(node.id, { width: 150, height: 40 }));
    edges.forEach((edge) => layout.setEdge(edge.source, edge.target));
    dagre.layout(layout);
    const flowNodes: Node<DiagramNode>[] = nodes.map((node) => {
      const point = layout.node(node.id);
      return {
        id: node.id,
        type: "card",
        position: { x: point.x - 75, y: point.y - 20 },
        width: 150,
        height: 40,
        data: { label: node.label, highlighted: focus.has(node.id), dimmed: focus.size > 0 && !focus.has(node.id) },
      };
    });
    const flowEdges: Edge[] = edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      style: { stroke: "#7c8bb8", strokeWidth: 1.3 },
    }));
    return { nodes: flowNodes, edges: flowEdges };
  }, [graph.data, highlight]);

  if (graph.loading) return <LoadingBlock label="Drawing modules" />;
  if (graph.error) return <ErrorAlert message={graph.error} />;
  if (!laid || laid.nodes.length === 0) return null;
  return (
    <div className="h-64 overflow-hidden rounded-lg border border-navy-700 bg-navy-950">
      <ReactFlow nodes={laid.nodes} edges={laid.edges} nodeTypes={diagramTypes} fitView fitViewOptions={{ padding: 0.15 }} nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
        <Background color="#1d2842" gap={24} size={1} />
      </ReactFlow>
    </div>
  );
}

function ResultPanel({ analysisId, question, result }: { analysisId: string; question: LearningQuestion; result: LearningAnswer }) {
  const highlight = useMemo(() => {
    const names = new Set<string>();
    if (question.module) names.add(question.module);
    if (question.mode === "architecture" || question.mode === "dependency") {
      result.correct_answer.forEach((name) => names.add(name));
    }
    return [...names];
  }, [question, result]);
  return (
    <div className="space-y-4 border-t border-navy-700 pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={result.correct ? "emerald" : "amber"}>{result.correct ? "Correct" : "Not quite"}</Badge>
        <Badge>{result.points === 1 ? "1 point" : result.points === 0.5 ? "½ point (hint used)" : "0 points"}</Badge>
      </div>
      <div className="grid gap-4 md:grid-cols-2 text-sm">
        <div>
          <p className="mb-1 text-xs text-ink-500">Your answer</p>
          <p className="text-ink-200">{result.your_answer.join(" → ") || "—"}</p>
        </div>
        <div>
          <p className="mb-1 text-xs text-ink-500">Correct answer</p>
          <p className="text-ink-200">{result.correct_answer.join(" → ")}</p>
        </div>
      </div>
      <p className="text-sm leading-7 text-ink-300">{result.explanation}</p>
      {question.kind === "order" && (
        <div className="flex flex-col items-start">
          {result.correct_answer.map((step, index) => {
            const right = result.your_answer[index] === step;
            return (
              <div key={step} className="flex w-full flex-col items-center">
                <div className={cx("w-full max-w-md rounded-lg border px-4 py-2.5 font-mono text-sm", right ? "border-emerald-400/40 bg-emerald-500/5 text-ink-100" : "border-amber-400/40 text-ink-200")}>
                  <span className="mr-3 text-xs text-ink-500">{index + 1}</span>
                  {step}
                </div>
                {index < result.correct_answer.length - 1 && <span className="my-1 text-ink-600" aria-hidden="true">↓</span>}
              </div>
            );
          })}
        </div>
      )}
      {(question.mode === "architecture" || question.mode === "dependency") && <ModuleDiagram analysisId={analysisId} highlight={highlight} />}
      <div className="flex flex-wrap gap-2">
        {result.evidence.map((item) => (
          <Link key={`${item.file}-${item.start_line}-${item.label}`} to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(item.file)}&line=${item.start_line}`} className="rounded-md border border-navy-600 px-2.5 py-1 text-xs text-ink-300 hover:border-accent/50 hover:text-ink-100">
            {item.file}, lines {item.start_line}–{item.end_line}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function LearnPage() {
  const { analysisId = "" } = useParams();
  const overview = useAsync(() => api.learningOverview(analysisId), [analysisId]);
  const files = useAsync(() => api.files(analysisId), [analysisId]);
  const [mode, setMode] = useState("mixed");
  const [difficulty, setDifficulty] = useState("");
  const [moduleName, setModuleName] = useState("");
  const [queue, setQueue] = useState<LearningQuestion[]>([]);
  const [current, setCurrent] = useState<LearningQuestion | null>(null);
  const [batchNote, setBatchNote] = useState<LearningBatch | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [order, setOrder] = useState<string[]>([]);
  const [hint, setHint] = useState<string | null>(null);
  const [result, setResult] = useState<LearningAnswer | null>(null);
  const [progress, setProgress] = useState<LearningProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openReview, setOpenReview] = useState<string | null>(null);

  useEffect(() => { rememberAnalysis(analysisId); }, [analysisId]);
  useEffect(() => { if (overview.data) setProgress(overview.data.progress); }, [overview.data]);

  const activeProgress = progress ?? overview.data?.progress ?? null;

  function resetQuestion() {
    setSelected([]);
    setOrder([]);
    setHint(null);
    setResult(null);
  }

  function loadQuestions(batch: LearningBatch) {
    setBatchNote(batch);
    const [first, ...rest] = batch.questions;
    setCurrent(first ?? null);
    setQueue(rest);
    resetQuestion();
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const batch = await api.learningGenerate(analysisId, {
        mode,
        difficulty: difficulty || undefined,
        module: moduleName || undefined,
        count: 5,
      });
      loadQuestions(batch);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  async function revealHint() {
    if (!current) return;
    try {
      const response = await api.learningHint(analysisId, current.id);
      setHint(response.hint);
    } catch (caught) {
      setError(errorText(caught));
    }
  }

  async function submit() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      const answer = current.kind === "choice" ? { selected } : { order };
      const response = await api.learningAnswer(analysisId, current.id, answer);
      setResult(response);
      setProgress(await api.learningProgress(analysisId));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  function next() {
    const [following, ...rest] = queue;
    setCurrent(following ?? null);
    setQueue(rest);
    resetQuestion();
  }

  function pickOption(id: string) {
    if (!current || result) return;
    if (current.kind === "choice") {
      setSelected([id]);
    } else if (!order.includes(id)) {
      setOrder([...order, id]);
    }
  }

  const textFor = (id: string) => current?.options.find((option) => option.id === id)?.text ?? id;
  const readyToSubmit = current ? (current.kind === "choice" ? selected.length === 1 : order.length === current.options.length) : false;
  const accuracy = activeProgress?.accuracy;

  return (
    <div className="space-y-6">
      <PageHeader
        title="CodeQuest"
        actions={
          activeProgress && (
            <div className="flex items-center gap-3 text-sm text-ink-300">
              <span>{activeProgress.points} {activeProgress.points === 1 ? "point" : "points"}</span>
              <span className="text-ink-600">·</span>
              <span>{activeProgress.answered} answered</span>
              {accuracy !== null && accuracy !== undefined && (<><span className="text-ink-600">·</span><span>{Math.round(accuracy * 100)}% correct</span></>)}
            </div>
          )
        }
      />

      <div className="flex flex-wrap items-end gap-4">
        <div className="w-56">
          <Field label="Practice" htmlFor="learn-mode">
            <select id="learn-mode" className={inputClass} value={mode} onChange={(event) => setMode(event.target.value)}>
              {(overview.data?.modes ?? [{ id: "mixed", label: "Mixed practice" }]).map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="w-44">
          <Field label="Level" htmlFor="learn-level">
            <select id="learn-level" className={inputClass} value={difficulty} onChange={(event) => setDifficulty(event.target.value)}>
              <option value="">Any</option>
              {(overview.data?.difficulties ?? []).map((item) => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}
            </select>
          </Field>
        </div>
        <div className="w-64">
          <Field label="Module" htmlFor="learn-module">
            <select id="learn-module" className={inputClass} value={moduleName} onChange={(event) => setModuleName(event.target.value)}>
              <option value="">All modules</option>
              {(overview.data?.modules ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </Field>
        </div>
        <Button onClick={() => void start()} loading={busy && !current}>Start practice</Button>
      </div>

      {error && <ErrorAlert message={error} />}
      {overview.loading && <LoadingBlock label="Loading" />}
      {overview.error && <ErrorAlert message={overview.error} onRetry={overview.reload} />}
      {files.error && <ErrorAlert message={files.error} onRetry={files.reload} />}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          {!current && batchNote && batchNote.questions.length === 0 && (
            <div className="space-y-2 py-6">
              <p className="text-sm text-ink-200">No questions for this choice yet.</p>
              {batchNote.reason && <p className="text-sm leading-6 text-ink-400">{batchNote.reason}</p>}
              <p className="text-sm text-ink-500">Try another practice type or level.</p>
            </div>
          )}
          {!current && !batchNote && <p className="py-10 text-center text-sm text-ink-400">Choose a practice type and start.</p>}
          {current && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{current.mode_label}</Badge>
                <Badge tone={DIFFICULTY_TONE[current.difficulty]}>{current.difficulty}</Badge>
                {current.module && <Badge>{current.module}</Badge>}
                <span className="text-xs text-ink-500">{current.source}</span>
                <span className="ml-auto text-xs text-ink-500">{queue.length + 1} left in this set</span>
              </div>
              <h2 className="text-base font-medium leading-7 text-ink-50">{current.prompt}</h2>
              {current.excerpt && (
                <div>
                  <p className="mb-2 font-mono text-xs text-ink-500">{current.excerpt.file}, from line {current.excerpt.start_line}</p>
                  <CodeView code={current.excerpt.text} startLine={current.excerpt.start_line} />
                </div>
              )}
              {current.kind === "order" && (
                <div className="rounded-lg border border-navy-700 p-4">
                  <p className="mb-3 text-xs text-ink-500">Your order</p>
                  {order.length === 0 && <p className="text-sm text-ink-500">Click the steps below in the order you think they run.</p>}
                  <ol className="space-y-2">
                    {order.map((id, index) => (
                      <li key={id} className="flex items-center gap-3">
                        <span className="grid h-6 w-6 place-items-center rounded-full bg-navy-700 text-xs text-ink-200">{index + 1}</span>
                        <span className="font-mono text-sm text-ink-100">{textFor(id)}</span>
                        {!result && (
                          <button type="button" onClick={() => setOrder(order.filter((item) => item !== id))} className="ml-auto text-xs text-ink-500 hover:text-ink-200">remove</button>
                        )}
                      </li>
                    ))}
                  </ol>
                  {!result && order.length > 0 && (
                    <button type="button" onClick={() => setOrder([])} className="mt-3 text-xs text-ink-500 hover:text-ink-200">Start over</button>
                  )}
                </div>
              )}
              <div className="grid gap-2">
                {current.options.map((option) => {
                  const picked = current.kind === "choice" ? selected.includes(option.id) : order.includes(option.id);
                  const correctOption = result ? result.correct_answer.includes(option.text) : false;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      disabled={Boolean(result) || (current.kind === "order" && picked)}
                      onClick={() => pickOption(option.id)}
                      className={cx(
                        "rounded-lg border px-4 py-3 text-left font-mono text-sm transition",
                        picked ? "border-accent bg-accent/10 text-ink-50" : "border-navy-700 text-ink-200 hover:border-navy-600",
                        result && correctOption && "border-emerald-400/50 bg-emerald-500/5",
                        result && picked && !correctOption && "border-amber-400/50",
                      )}
                    >
                      {option.text}
                    </button>
                  );
                })}
              </div>
              {hint && <p className="rounded-lg bg-navy-900 px-4 py-3 text-sm text-ink-300">Hint: {hint}</p>}
              {!result && (
                <div className="flex flex-wrap gap-3">
                  <Button variant="secondary" onClick={() => void revealHint()} disabled={Boolean(hint)}>Show a hint</Button>
                  <Button onClick={() => void submit()} disabled={!readyToSubmit} loading={busy && Boolean(current)}>Check answer</Button>
                </div>
              )}
              {result && (
                <>
                  <ResultPanel analysisId={analysisId} question={current} result={result} />
                  <Button onClick={next} disabled={queue.length === 0 && !result}>{queue.length > 0 ? "Next question" : "Set complete"}</Button>
                </>
              )}
            </div>
          )}
        </Card>

        <aside className="space-y-5">
          <Card>
            <CardHeader title="Progress" />
            {activeProgress ? (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <dt className="text-ink-500">Points</dt><dd className="text-ink-100">{activeProgress.points}</dd>
                <dt className="text-ink-500">Answered</dt><dd className="text-ink-100">{activeProgress.answered}</dd>
                <dt className="text-ink-500">Correct</dt><dd className="text-ink-100">{activeProgress.correct}</dd>
                <dt className="text-ink-500">Accuracy</dt><dd className="text-ink-100">{accuracy === null || accuracy === undefined ? "—" : `${Math.round(accuracy * 100)}%`}</dd>
              </dl>
            ) : <LoadingBlock />}
            {activeProgress && Object.keys(activeProgress.by_mode).length > 0 && (
              <ul className="mt-5 space-y-2 border-t border-navy-700 pt-4 text-sm">
                {Object.entries(activeProgress.by_mode).map(([key, value]) => (
                  <li key={key} className="flex justify-between text-ink-300">
                    <span>{overview.data?.modes.find((item) => item.id === key)?.label ?? key}</span>
                    <span className="tabular-nums">{value.correct}/{value.answered}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="To review" />
            {activeProgress && activeProgress.review.length === 0 && <p className="text-sm text-ink-400">Nothing to review yet.</p>}
            <ul className="space-y-2">
              {activeProgress?.review.map((item) => (
                <li key={item.question_id} className="rounded-lg border border-navy-700">
                  <button type="button" onClick={() => setOpenReview(openReview === item.question_id ? null : item.question_id)} className="w-full px-3 py-2.5 text-left">
                    <span className="block text-xs text-ink-500">{item.mode_label}</span>
                    <span className="block text-sm text-ink-200">{item.prompt}</span>
                  </button>
                  {openReview === item.question_id && (
                    <div className="space-y-2 border-t border-navy-700 px-3 py-3 text-sm">
                      <p className="text-ink-300">Correct answer: <span className="text-ink-100">{item.correct_answer.join(" → ")}</span></p>
                      <p className="leading-6 text-ink-400">{item.explanation}</p>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}
