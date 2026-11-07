import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { Network } from "lucide-react";
import dagre from "dagre";
import { api } from "../lib/api";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import type { GraphEdge, GraphNode } from "../types";
import { Button, ConfidenceBadge, EmptyState, ErrorAlert, Field, LoadingBlock, PageHeader, cx, inputClass } from "../components/ui";

const NODE_WIDTH = 200;
const NODE_HEIGHT = 54;
const DEFAULT_LIMIT = 14;
const ALL_LIMIT = 200;
const EXACT_COLOR = "#7c8bb8";
const NAME_COLOR = "#fbbf24";
const LAZY_COLOR = "#64748b";

interface CardData extends Record<string, unknown> {
  title: string;
  subtitle: string;
  inCycle: boolean;
  selected: boolean;
}

function GraphCard({ data }: NodeProps<Node<CardData>>) {
  return (
    <div
      className={cx(
        "flex h-full flex-col justify-center rounded-lg border bg-navy-850 px-3.5 shadow-lg shadow-black/30",
        data.selected ? "border-accent ring-2 ring-accent/30" : data.inCycle ? "border-amber-400/60" : "border-navy-600",
      )}
    >
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-navy-600" />
      <p className="truncate text-[13px] font-medium text-ink-50" title={data.title}>{data.title}</p>
      <p className="truncate text-[11px] text-ink-500" title={data.subtitle}>{data.subtitle}</p>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-navy-600" />
    </div>
  );
}

const nodeTypes = { card: GraphCard };

function edgeStyle(edge: GraphEdge): Partial<Edge> {
  if (edge.confidence === "approximate") {
    return { style: { stroke: NAME_COLOR, strokeWidth: 1.3, strokeDasharray: "5 4" }, markerEnd: { type: MarkerType.ArrowClosed, color: NAME_COLOR, width: 14, height: 14 } };
  }
  if (edge.lazy) {
    return { style: { stroke: LAZY_COLOR, strokeWidth: 1.2, strokeDasharray: "2 4" }, markerEnd: { type: MarkerType.ArrowClosed, color: LAZY_COLOR, width: 14, height: 14 } };
  }
  return { style: { stroke: EXACT_COLOR, strokeWidth: 1.4 }, markerEnd: { type: MarkerType.ArrowClosed, color: EXACT_COLOR, width: 14, height: 14 } };
}

export function DependencyPage() {
  const { analysisId = "" } = useParams();
  const navigate = useNavigate();
  const files = useAsync(() => api.files(analysisId), [analysisId]);
  const [scope, setScope] = useState<"modules" | "functions">("modules");
  const [moduleChoice, setModuleChoice] = useState("");
  const [includeNameMatches, setIncludeNameMatches] = useState(false);
  const [search, setSearch] = useState("");
  const [focusId, setFocusId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { rememberAnalysis(analysisId); }, [analysisId]);

  const modules = useMemo(() => [...new Set((files.data ?? []).map((item) => item.module))].sort(), [files.data]);
  const ready = scope === "modules" || Boolean(moduleChoice);

  const graph = useAsync(
    () => api.dependencies(analysisId, {
      scope,
      confidence: includeNameMatches ? "all" : "confirmed",
      max_nodes: showAll ? ALL_LIMIT : DEFAULT_LIMIT,
      module: scope === "functions" ? moduleChoice : undefined,
      q: search.trim() || undefined,
    }),
    [analysisId, scope, moduleChoice, includeNameMatches, search, showAll],
    ready,
  );

  const view = useMemo(() => {
    const data = graph.data;
    if (!data) return null;
    const ids = new Set(data.nodes.map((node) => node.id));
    const edges = data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && edge.source !== edge.target);
    if (!focusId) return { nodes: data.nodes, edges, truncated: data.truncated, total: data.total_nodes };
    const keep = new Set<string>([focusId]);
    edges.forEach((edge) => {
      if (edge.source === focusId || edge.target === focusId) {
        keep.add(edge.source);
        keep.add(edge.target);
      }
    });
    return {
      nodes: data.nodes.filter((node) => keep.has(node.id)),
      edges: edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target)),
      truncated: false,
      total: keep.size,
    };
  }, [graph.data, focusId]);

  const laid = useMemo(() => {
    if (!view) return null;
    const layout = new dagre.graphlib.Graph();
    layout.setGraph({ rankdir: "TB", nodesep: 22, ranksep: 64, marginx: 24, marginy: 24 });
    layout.setDefaultEdgeLabel(() => ({}));
    view.nodes.forEach((node) => layout.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
    view.edges.forEach((edge) => layout.setEdge(edge.source, edge.target));
    dagre.layout(layout);
    return layout;
  }, [view]);

  const flowNodes = useMemo<Node<CardData>[]>(() => {
    if (!view || !laid) return [];
    return view.nodes.map((node: GraphNode) => {
      const point = laid.node(node.id);
      const subtitle = scope === "modules"
        ? `${node.fan_out ?? 0} imports · ${node.fan_in ?? 0} used by`
        : node.file ?? "";
      return {
        id: node.id,
        type: "card",
        position: { x: point.x - NODE_WIDTH / 2, y: point.y - NODE_HEIGHT / 2 },
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        data: { title: node.label, subtitle, inCycle: Boolean(node.in_cycle), selected: node.id === selectedId },
      };
    });
  }, [view, laid, scope, selectedId]);

  const flowEdges = useMemo<Edge[]>(() => {
    if (!view) return [];
    return view.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, type: "smoothstep", ...edgeStyle(edge) }));
  }, [view]);

  const moduleDetail = useAsync(() => api.moduleDependencies(analysisId, selectedId as string), [analysisId, selectedId], Boolean(selectedId) && scope === "modules");
  const symbolDetail = useAsync(() => api.symbolDetail(analysisId, selectedId as string), [analysisId, selectedId], Boolean(selectedId) && scope === "functions");
  const selectedNode = view?.nodes.find((node) => node.id === selectedId);

  function changeScope(next: "modules" | "functions") {
    setScope(next);
    setSelectedId(null);
    setFocusId(null);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Dependency Graph"
        actions={
          <div className="flex rounded-lg border border-navy-600 bg-navy-900 p-0.5">
            {(["modules", "functions"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => changeScope(value)}
                className={cx("rounded-md px-3 py-1.5 text-sm capitalize", scope === value ? "bg-navy-700 text-ink-50" : "text-ink-400 hover:text-ink-100")}
              >
                {value}
              </button>
            ))}
          </div>
        }
      />

      <div className="flex flex-wrap items-end gap-4">
        {scope === "functions" && (
          <div className="w-64">
            <Field label="Module" htmlFor="graph-module">
              <select id="graph-module" className={inputClass} value={moduleChoice} onChange={(event) => { setModuleChoice(event.target.value); setSelectedId(null); setFocusId(null); }}>
                <option value="">Choose a module</option>
                {modules.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </Field>
          </div>
        )}
        <div className="w-64">
          <Field label="Find" htmlFor="graph-search">
            <input id="graph-search" className={inputClass} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name or file" />
          </Field>
        </div>
        <label className="flex cursor-pointer items-center gap-2 pb-2 text-sm text-ink-300">
          <input type="checkbox" checked={includeNameMatches} onChange={(event) => setIncludeNameMatches(event.target.checked)} className="h-4 w-4 accent-[#fbbf24]" />
          Show name matches
        </label>
        {focusId && <Button variant="secondary" onClick={() => setFocusId(null)}>Show all</Button>}
      </div>

      {!ready && <EmptyState icon={Network} title="Choose a module to see its functions." />}
      {ready && graph.loading && <LoadingBlock label="Building graph" />}
      {ready && graph.error && <ErrorAlert message={graph.error} onRetry={graph.reload} />}

      {ready && view && view.nodes.length === 0 && !graph.loading && (
        <EmptyState icon={Network} title="No connections to show." />
      )}

      {ready && view && view.nodes.length > 0 && (
        <div className={cx("grid gap-4", selectedNode && "xl:grid-cols-[minmax(0,1fr)_300px]")}>
          <div className="relative h-[66vh] min-h-[420px] overflow-hidden rounded-xl border border-navy-700 bg-navy-950">
            <ReactFlow
              key={`${scope}-${moduleChoice}-${focusId}-${includeNameMatches}-${search}`}
              nodes={flowNodes}
              edges={flowEdges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.12 }}
              minZoom={0.25}
              maxZoom={1.5}
              nodesDraggable={false}
              nodesConnectable={false}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              onPaneClick={() => setSelectedId(null)}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#1d2842" gap={24} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
            <div className="pointer-events-none absolute left-4 top-3 flex flex-wrap items-center gap-5 text-[11px] text-ink-400">
              <span className="flex items-center gap-2"><span className="h-0.5 w-6" style={{ background: EXACT_COLOR }} />Exact link</span>
              <span className="flex items-center gap-2"><span className="w-6 border-t border-dashed" style={{ borderColor: NAME_COLOR }} />Name match</span>
              {view.truncated && (
                <span>
                  Showing {view.nodes.length} of {view.total}.{" "}
                  {showAll ? "Use Find to narrow it." : <button type="button" onClick={() => setShowAll(true)} className="pointer-events-auto text-accent hover:underline">Show all</button>}
                </span>
              )}
            </div>
          </div>

          <aside className={cx("rounded-xl border border-navy-700 bg-navy-850/80 p-5 text-sm", !selectedNode && "hidden")}>
            {selectedNode && (
              <div className="space-y-5">
                <div>
                  <p className="font-medium text-ink-50">{selectedNode.label}</p>
                  <p className="mt-0.5 break-all text-xs text-ink-500">{selectedNode.file}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {focusId !== selectedNode.id && <Button variant="secondary" onClick={() => setFocusId(selectedNode.id)}>Show only connections</Button>}
                  <Button
                    variant="ghost"
                    onClick={() => navigate(`/analyses/${analysisId}/explorer?path=${encodeURIComponent(selectedNode.file ?? "")}&line=${selectedNode.line ?? 1}`)}
                  >
                    Open in explorer
                  </Button>
                </div>

                {scope === "modules" && moduleDetail.data && (
                  <>
                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500">Imports ({moduleDetail.data.imports.length})</p>
                      <ul className="space-y-1.5">
                        {moduleDetail.data.imports.map((item) => (
                          <li key={`${item.module}-${item.line}`} className="flex items-center justify-between gap-2 font-mono text-xs text-ink-200">
                            <span className="truncate">{item.module}</span>
                            {item.lazy && <span className="text-[10px] text-ink-500">inside function</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500">Used by ({moduleDetail.data.imported_by.length})</p>
                      <ul className="space-y-1.5">
                        {moduleDetail.data.imported_by.map((item) => (
                          <li key={`${item.module}-${item.line}`} className="truncate font-mono text-xs text-ink-200">{item.module}</li>
                        ))}
                      </ul>
                    </div>
                  </>
                )}

                {scope === "functions" && symbolDetail.data && (
                  <>
                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500">Calls ({symbolDetail.data.callees.length})</p>
                      <ul className="space-y-1.5">
                        {symbolDetail.data.callees.map((item) => (
                          <li key={`${item.line}-${item.target_name}`} className="flex items-center justify-between gap-2 text-xs">
                            <span className="truncate font-mono text-ink-200">{item.target_name}</span>
                            <ConfidenceBadge confidence={item.confidence} />
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500">Called by ({symbolDetail.data.callers.length})</p>
                      <ul className="space-y-1.5">
                        {symbolDetail.data.callers.map((item) => (
                          <li key={`${item.line}-${item.source_name}`} className="flex items-center justify-between gap-2 text-xs">
                            <span className="truncate font-mono text-ink-200">{item.source_name}</span>
                            <ConfidenceBadge confidence={item.confidence} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  </>
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
