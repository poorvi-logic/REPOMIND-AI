import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen, Search } from "lucide-react";
import { api } from "../lib/api";
import { errorText } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import type { ExplanationResponse, FileRow, Finding } from "../types";
import { Button, ConfidenceBadge, ErrorAlert, LoadingBlock, SeverityBadge, SourceBadge, cx, inputClass } from "../components/ui";
import { CodeView } from "../components/CodeView";

interface TreeDirectory {
  name: string;
  path: string;
  directories: Map<string, TreeDirectory>;
  files: FileRow[];
}

function buildTree(files: FileRow[]): TreeDirectory {
  const root: TreeDirectory = { name: "", path: "", directories: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    parts.slice(0, -1).forEach((part, index) => {
      const path = parts.slice(0, index + 1).join("/");
      let child = node.directories.get(part);
      if (!child) {
        child = { name: part, path, directories: new Map(), files: [] };
        node.directories.set(part, child);
      }
      node = child;
    });
    node.files.push(file);
  }
  return root;
}

function directoryPaths(node: TreeDirectory, acc: string[] = []): string[] {
  node.directories.forEach((child) => {
    acc.push(child.path);
    directoryPaths(child, acc);
  });
  return acc;
}

function TreeView({ node, depth, selected, expanded, filter, onToggle, onSelect }: {
  node: TreeDirectory; depth: number; selected: string; expanded: Set<string>; filter: string;
  onToggle: (path: string) => void; onSelect: (path: string) => void;
}) {
  const matches = (path: string) => !filter || path.toLowerCase().includes(filter.toLowerCase());
  return (
    <ul className="space-y-0.5">
      {[...node.directories.values()].sort((a, b) => a.name.localeCompare(b.name)).map((directory) => {
        const open = expanded.has(directory.path) || Boolean(filter);
        return (
          <li key={directory.path}>
            <button type="button" onClick={() => onToggle(directory.path)} className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs text-ink-300 hover:bg-navy-800" style={{ paddingLeft: 6 + depth * 12 }}>
              {open ? <ChevronDown className="h-3 w-3" aria-hidden="true" /> : <ChevronRight className="h-3 w-3" aria-hidden="true" />}
              {open ? <FolderOpen className="h-3.5 w-3.5 text-ink-500" aria-hidden="true" /> : <Folder className="h-3.5 w-3.5 text-ink-500" aria-hidden="true" />}
              <span className="truncate">{directory.name}</span>
            </button>
            {open && <TreeView node={directory} depth={depth + 1} selected={selected} expanded={expanded} filter={filter} onToggle={onToggle} onSelect={onSelect} />}
          </li>
        );
      })}
      {node.files.filter((file) => matches(file.path)).sort((a, b) => a.path.localeCompare(b.path)).map((file) => (
        <li key={file.path}>
          <button
            type="button"
            onClick={() => onSelect(file.path)}
            className={cx("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs", selected === file.path ? "bg-navy-700 text-ink-50" : "text-ink-300 hover:bg-navy-800 hover:text-ink-100")}
            style={{ paddingLeft: 6 + depth * 12 + 16 }}
          >
            <FileCode2 className="h-3.5 w-3.5 shrink-0 text-ink-500" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{file.path.split("/").pop()}</span>
            {file.findings > 0 && <span className="text-[10px] tabular-nums text-amber-300">{file.findings}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

type Tab = "functions" | "imports" | "issues" | "details";

export function ExplorerPage() {
  const { analysisId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedPath = searchParams.get("path");
  const requestedLine = Number(searchParams.get("line")) || null;
  const files = useAsync(() => api.files(analysisId), [analysisId]);
  const [selectedPath, setSelectedPath] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [searchMode, setSearchMode] = useState<"files" | "names" | "text" | "imports">("files");
  const found = useAsync(async () => {
    const query = filter.trim();
    if (searchMode === "names") {
      return (await api.symbols(analysisId, { q: query, limit: 200 })).map((item) => ({
        key: item.id, title: item.qualname, file: item.file ?? "", line: item.line, detail: item.kind.replace("_", " "),
      }));
    }
    if (searchMode === "text") {
      return (await api.textSearch(analysisId, query)).results.map((item) => ({
        key: `${item.file}:${item.line}`, title: item.text, file: item.file, line: item.line, detail: item.symbol ?? "",
      }));
    }
    if (searchMode === "imports") {
      return (await api.importSearch(analysisId, query)).results.map((item) => ({
        key: `${item.file}:${item.line}`, title: item.statement, file: item.file, line: item.line, detail: item.module,
      }));
    }
    return [];
  }, [analysisId, searchMode, filter], searchMode !== "files" && filter.trim().length > 0);
  const [tab, setTab] = useState<Tab>("functions");
  const [symbolId, setSymbolId] = useState<string | null>(null);
  const [scrollLine, setScrollLine] = useState<number | null>(requestedLine);
  const [summary, setSummary] = useState<ExplanationResponse | null>(null);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [symbolExplanation, setSymbolExplanation] = useState<ExplanationResponse | null>(null);
  const [symbolBusy, setSymbolBusy] = useState(false);

  useEffect(() => { rememberAnalysis(analysisId); }, [analysisId]);

  useEffect(() => {
    if (!files.data || files.data.length === 0) return;
    const preferred = requestedPath && files.data.some((file) => file.path === requestedPath) ? requestedPath : files.data[0].path;
    setSelectedPath(preferred);
    setExpanded(new Set(directoryPaths(buildTree(files.data))));
  }, [files.data, requestedPath]);

  const source = useAsync(() => api.source(analysisId, selectedPath), [analysisId, selectedPath], Boolean(selectedPath));
  const detail = useAsync(() => api.fileDetail(analysisId, selectedPath), [analysisId, selectedPath], Boolean(selectedPath));
  const symbol = useAsync(() => api.symbolDetail(analysisId, symbolId as string), [analysisId, symbolId], Boolean(symbolId));
  const tree = useMemo(() => (files.data ? buildTree(files.data) : null), [files.data]);

  useEffect(() => {
    setSummary(null);
    setSummaryError(null);
    setSymbolId(null);
    setSymbolExplanation(null);
  }, [selectedPath]);

  useEffect(() => {
    if (symbol.data) setTab("details");
  }, [symbol.data]);

  async function summarizeFile() {
    setSummaryBusy(true);
    setSummaryError(null);
    try {
      setSummary(await api.explainFile(analysisId, selectedPath));
    } catch (caught) {
      setSummaryError(errorText(caught));
    } finally {
      setSummaryBusy(false);
    }
  }

  async function explainSymbol() {
    if (!symbolId) return;
    setSymbolBusy(true);
    try {
      setSymbolExplanation(await api.explainSymbol(analysisId, symbolId));
    } catch (caught) {
      setSymbolExplanation({ text: errorText(caught), mode: "deterministic", ai_status: "api_error", model: null, references: [] });
    } finally {
      setSymbolBusy(false);
    }
  }

  function selectFile(path: string) {
    setSelectedPath(path);
    setScrollLine(null);
    setSearchParams({ path });
  }

  function openIssue(finding: Finding) {
    setScrollLine(finding.line);
    setSearchParams({ path: finding.file, line: String(finding.line) });
    setTab("issues");
  }

  const range: [number, number] | null = symbol.data ? [symbol.data.source.start_line, symbol.data.source.end_line] : null;
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "functions", label: "Functions", count: detail.data?.symbols.length },
    { id: "imports", label: "Imports", count: detail.data?.imports.length },
    { id: "issues", label: "Issues", count: detail.data?.findings.length },
    { id: "details", label: "Details" },
  ];

  return (
    <div className="grid gap-4 xl:grid-cols-[250px_minmax(0,1fr)_340px]">
      {files.loading && <LoadingBlock label="Loading files" />}
      {files.error && <ErrorAlert message={files.error} onRetry={files.reload} />}
      {tree && (
        <aside className="flex max-h-[80vh] flex-col rounded-xl border border-navy-700 bg-navy-850/80 p-3">
          <select aria-label="Search in" value={searchMode} onChange={(event) => setSearchMode(event.target.value as typeof searchMode)} className={cx(inputClass, "mb-2 py-1.5 text-xs")}>
            <option value="files">File names</option>
            <option value="names">Function and class names</option>
            <option value="text">Source text</option>
            <option value="imports">Imports</option>
          </select>
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-500" aria-hidden="true" />
            <label htmlFor="tree-filter" className="sr-only">Filter files</label>
            <input id="tree-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={searchMode === "files" ? "File name" : "Search the project"} className={cx(inputClass, "py-1.5 pl-8 text-xs")} />
          </div>
          {searchMode !== "files" && filter.trim() && (
            <div className="scrollbar-thin mb-2 max-h-[60vh] space-y-1 overflow-y-auto">
              {found.loading && <LoadingBlock label="Searching" />}
              {found.error && <ErrorAlert message={found.error} />}
              {found.data && found.data.length === 0 && <p className="px-2 py-3 text-sm text-ink-500">No matches.</p>}
              {found.data?.map((row) => (
                <button key={row.key} type="button" onClick={() => { selectFile(row.file); setScrollLine(row.line); }} className="w-full rounded-md px-2 py-2 text-left hover:bg-navy-800">
                  <span className="block truncate font-mono text-xs text-ink-100">{row.title}</span>
                  <span className="block truncate text-[11px] text-ink-500">{row.file}, line {row.line}{row.detail ? ` · ${row.detail}` : ""}</span>
                </button>
              ))}
            </div>
          )}
          <div className={cx("scrollbar-thin flex-1 overflow-y-auto", searchMode !== "files" && filter.trim() && "hidden")}>
            <TreeView
              node={tree}
              depth={0}
              selected={selectedPath}
              expanded={expanded}
              filter={filter}
              onSelect={selectFile}
              onToggle={(path) => setExpanded((current) => {
                const next = new Set(current);
                if (next.has(path)) next.delete(path); else next.add(path);
                return next;
              })}
            />
          </div>
        </aside>
      )}

      <div className="min-w-0 space-y-4">
        {source.loading && <LoadingBlock label="Loading source" />}
        {source.error && <ErrorAlert message={source.error} onRetry={source.reload} />}
        {source.data && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="min-w-0 truncate font-mono text-sm text-ink-200">{selectedPath}</p>
              <Button variant="secondary" loading={summaryBusy} onClick={() => void summarizeFile()}>Summarize</Button>
            </div>
            <CodeView code={source.data.content} highlight={range ?? (scrollLine ? [scrollLine, scrollLine] : null)} scrollToLine={scrollLine} />
          </>
        )}
        {summaryBusy && <LoadingBlock label="Writing summary" />}
        {summaryError && <ErrorAlert message={summaryError} />}
        {summary && (
          <div className="rounded-xl border border-navy-700 bg-navy-850/80 p-5">
            <div className="mb-3"><SourceBadge mode={summary.mode} status={summary.ai_status} /></div>
            <p className="whitespace-pre-wrap text-sm leading-7 text-ink-200">{summary.text}</p>
          </div>
        )}
      </div>

      <aside className="flex max-h-[80vh] flex-col rounded-xl border border-navy-700 bg-navy-850/80 p-4">
        <div role="tablist" className="mb-4 grid grid-cols-4 gap-1 rounded-lg bg-navy-950 p-1">
          {tabs.map((item) => (
            <button
              key={item.id}
              role="tab"
              aria-selected={tab === item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={cx("rounded-md px-1 py-1.5 text-[11px] font-medium", tab === item.id ? "bg-navy-700 text-ink-50" : "text-ink-400 hover:text-ink-100")}
            >
              {item.label}{item.count !== undefined ? ` ${item.count}` : ""}
            </button>
          ))}
        </div>
        <div className="scrollbar-thin flex-1 space-y-2 overflow-y-auto pr-1">
          {detail.loading && <LoadingBlock label="Loading" />}
          {detail.error && <ErrorAlert message={detail.error} />}

          {tab === "functions" && detail.data && (
            <>
              {detail.data.symbols.length === 0 && <p className="text-sm text-ink-400">Nothing is defined in this file.</p>}
              {detail.data.symbols.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSymbolId(item.id)}
                  className={cx("w-full rounded-lg border px-3 py-2.5 text-left", symbolId === item.id ? "border-accent/50 bg-navy-800" : "border-navy-700 hover:border-navy-600")}
                >
                  <div className="flex items-center gap-2 text-[11px] text-ink-500">
                    <span className="capitalize">{item.kind.replace("_", " ")}</span>
                    {item.is_async && <span>async</span>}
                    <span className="ml-auto">line {item.line}</span>
                  </div>
                  <p className="mt-1 truncate font-mono text-xs text-ink-100">{item.qualname}</p>
                </button>
              ))}
            </>
          )}

          {tab === "imports" && detail.data && (
            <>
              {detail.data.imports.length === 0 && <p className="text-sm text-ink-400">No imports in this file.</p>}
              {detail.data.imports.map((item, index) => (
                <div key={`${item.line}-${index}`} className="flex items-center justify-between gap-2 rounded-lg border border-navy-700 px-3 py-2 text-xs">
                  <span className="truncate font-mono text-ink-200">
                    {item.kind === "from" ? `from ${".".repeat(item.level)}${item.module} import ${item.symbol}` : `import ${item.module}`}
                  </span>
                  <span className="shrink-0 text-ink-500">{item.lazy ? "in function" : `line ${item.line}`}</span>
                </div>
              ))}
              {detail.data.module_dependencies.imported_by.length > 0 && (
                <div className="rounded-lg border border-navy-700 p-3 text-xs">
                  <p className="mb-2 text-ink-500">Used by</p>
                  {detail.data.module_dependencies.imported_by.map((item) => <p key={item.module} className="font-mono text-ink-200">{item.module}</p>)}
                </div>
              )}
            </>
          )}

          {tab === "issues" && detail.data && (
            <>
              {detail.data.findings.length === 0 && <p className="text-sm text-ink-400">No issues in this file.</p>}
              {detail.data.findings.map((finding) => (
                <button key={finding.id} type="button" onClick={() => openIssue(finding)} className="w-full rounded-lg border border-navy-700 px-3 py-2.5 text-left hover:border-navy-600">
                  <div className="flex items-center gap-2"><SeverityBadge severity={finding.severity} /></div>
                  <p className="mt-1.5 text-xs text-ink-100">{finding.title}</p>
                  <p className="mt-0.5 text-[11px] text-ink-500">line {finding.line}</p>
                </button>
              ))}
            </>
          )}

          {tab === "details" && (
            <>
              {!symbolId && <p className="text-sm text-ink-400">Select a function on the Functions tab.</p>}
              {symbol.loading && <LoadingBlock label="Loading" />}
              {symbol.error && <ErrorAlert message={symbol.error} />}
              {symbol.data && (
                <div className="space-y-5 text-xs">
                  <div>
                    <p className="font-mono text-sm text-ink-50">{symbol.data.qualname}</p>
                    <p className="mt-1 text-ink-500">Lines {symbol.data.line} to {symbol.data.end_line}</p>
                    {symbol.data.docstring && <p className="mt-2 leading-5 text-ink-300">{symbol.data.docstring}</p>}
                  </div>
                  {symbol.data.arguments.length > 0 && (
                    <div>
                      <p className="mb-2 text-ink-500">Inputs</p>
                      <ul className="space-y-1 font-mono text-ink-200">
                        {symbol.data.arguments.map((arg) => (
                          <li key={arg.name}>{arg.name}{arg.annotation ? `: ${arg.annotation}` : ""}{arg.default ? " (optional)" : ""}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {symbol.data.returns && <p className="text-ink-300">Returns <span className="font-mono text-ink-200">{symbol.data.returns}</span></p>}
                  <LinkList title="Calls" items={symbol.data.callees.map((item) => ({ key: `${item.line}-${item.target_name}`, name: item.target_name ?? "", confidence: item.confidence }))} />
                  <LinkList title="Called by" items={symbol.data.callers.map((item) => ({ key: `${item.line}-${item.source_name}`, name: item.source_name ?? "", confidence: item.confidence }))} />
                  <Button variant="secondary" className="w-full" loading={symbolBusy} onClick={() => void explainSymbol()}>Explain this function</Button>
                  {symbolExplanation && (
                    <div className="space-y-2 rounded-lg border border-navy-700 p-3">
                      <SourceBadge mode={symbolExplanation.mode} status={symbolExplanation.ai_status} />
                      <p className="whitespace-pre-wrap leading-6 text-ink-200">{symbolExplanation.text}</p>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function LinkList({ title, items }: { title: string; items: { key: string; name: string; confidence: string }[] }) {
  return (
    <div>
      <p className="mb-2 text-ink-500">{title} ({items.length})</p>
      {items.length === 0 && <p className="text-ink-500">None</p>}
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li key={item.key} className="flex items-center justify-between gap-2">
            <span className="truncate font-mono text-ink-200">{item.name}</span>
            <ConfidenceBadge confidence={item.confidence} />
          </li>
        ))}
      </ul>
    </div>
  );
}
