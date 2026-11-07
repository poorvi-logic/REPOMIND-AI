import type {
  AIStatus, AnalysisMeta, AppConfig, AskResponse, ConversationDetail, ConversationMessage, ConversationSummary,
  LearningAnswer, LearningBatch, LearningOverview, LearningProgress,
  DependencyGraph, ExplanationResponse, FileDetail, FileRow, FlowNode, ImportHit, JiraIssueStatus, JiraPreview,
  JiraProject, JiraStatus, JiraTicketRecord, McpStatus, McpTool, Overview, Preferences, RiskListResponse, SearchHit,
  SymbolDetail, SymbolRow, TextHit,
} from "../types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type RequestOptions = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit | null };

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : "Invalid value"))
        .join("; ");
    }
  }
  return `The request failed (${status}).`;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | null | undefined = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  let response: Response;
  try {
    response = await fetch(path, { ...options, headers: { ...headers, ...(options.headers as Record<string, string>) }, body });
  } catch {
    throw new ApiError("Cannot reach the RepoMind server. Check that it is running.", 0);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(errorMessage(payload, response.status), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const segment = (value: string) => encodeURIComponent(value);
const query = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  config: () => request<AppConfig>("/api/meta/config"),
  preferences: () => request<Preferences>("/api/settings"),
  savePreferences: (values: Partial<Preferences>) => request<Preferences>("/api/settings", { method: "PUT", json: values }),
  aiStatus: () => request<AIStatus>("/api/ai/status"),
  aiConnect: (apiKey: string) => request<AIStatus>("/api/ai/connection", { method: "POST", json: { api_key: apiKey } }),
  aiDisconnect: () => request<AIStatus>("/api/ai/connection", { method: "DELETE" }),
  mcpTools: () => request<McpTool[]>("/api/mcp/tools"),
  mcpConfig: () => request<{ mcpServers: Record<string, unknown> }>("/api/mcp/config"),

  listAnalyses: () => request<AnalysisMeta[]>("/api/analyses"),
  getAnalysis: (id: string) => request<AnalysisMeta>(`/api/analyses/${segment(id)}`),
  overview: (id: string) => request<Overview>(`/api/analyses/${segment(id)}/overview`),
  deleteAnalysis: (id: string) => request<{ deleted: string }>(`/api/analyses/${segment(id)}`, { method: "DELETE" }),
  uploadArchive: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<AnalysisMeta>("/api/analyses/upload", { method: "POST", body: form });
  },
  analyzeGithub: (url: string) => request<AnalysisMeta>("/api/analyses/github", { method: "POST", json: { url } }),
  createReport: (id: string) => request<{ download_url: string }>(`/api/analyses/${segment(id)}/report`, { method: "POST" }),
  reportUrl: (id: string) => `/api/analyses/${segment(id)}/report/download`,

  files: (id: string) => request<FileRow[]>(`/api/analyses/${segment(id)}/files`),
  fileDetail: (id: string, path: string) => request<FileDetail>(`/api/analyses/${segment(id)}/file${query({ path })}`),
  source: (id: string, path: string) => request<{ path: string; content: string; lines: number }>(`/api/analyses/${segment(id)}/source${query({ path })}`),
  symbols: (id: string, params: { q?: string; file?: string; limit?: number } = {}) =>
    request<SymbolRow[]>(`/api/analyses/${segment(id)}/symbols${query(params)}`),
  symbolDetail: (id: string, symbolId: string) =>
    request<SymbolDetail>(`/api/analyses/${segment(id)}/symbols/${symbolId.split("/").map(segment).join("/")}`),
  dependencies: (id: string, params: { scope: "modules" | "functions"; confidence: "confirmed" | "all"; max_nodes: number; focus?: string; q?: string; module?: string }) =>
    request<DependencyGraph>(`/api/analyses/${segment(id)}/dependencies${query(params)}`),
  moduleDependencies: (id: string, module: string) =>
    request<{
      module: string;
      file: string;
      imports: { module: string; line: number; lazy: boolean; names: string[] }[];
      imported_by: { module: string; line: number; lazy: boolean }[];
      in_cycle: boolean;
    }>(`/api/analyses/${segment(id)}/modules/${segment(module)}/dependencies`),
  callFlow: (id: string, symbolId: string, depth: number) =>
    request<{ root: string; depth: number; tree: FlowNode; lines: string[]; truncated: boolean }>(
      `/api/analyses/${segment(id)}/call-flow${query({ symbol_id: symbolId, depth })}`,
    ),
  risks: (id: string, params: { min_severity?: string; category?: string } = {}) =>
    request<RiskListResponse>(`/api/analyses/${segment(id)}/risks${query(params)}`),
  riskDetail: (id: string, findingId: string) =>
    request<RiskListResponse["findings"][number] & { context: { line: number; text: string }[] }>(
      `/api/analyses/${segment(id)}/risks/${segment(findingId)}`,
    ),
  search: (id: string, q: string) =>
    request<{ query: string; method: string; note: string | null; results: SearchHit[] }>(`/api/analyses/${segment(id)}/search${query({ q, limit: 12 })}`),
  ask: (id: string, question: string) => request<AskResponse>(`/api/analyses/${segment(id)}/ask`, { method: "POST", json: { question } }),

  explainFile: (id: string, path: string) => request<ExplanationResponse>(`/api/analyses/${segment(id)}/explain/file`, { method: "POST", json: { path } }),
  explainSymbol: (id: string, symbolId: string) =>
    request<ExplanationResponse>(`/api/analyses/${segment(id)}/explain/symbol`, { method: "POST", json: { symbol_id: symbolId } }),
  explainArchitecture: (id: string) => request<ExplanationResponse>(`/api/analyses/${segment(id)}/explain/architecture`, { method: "POST" }),
  explainFinding: (id: string, findingId: string) =>
    request<ExplanationResponse>(`/api/analyses/${segment(id)}/explain/finding`, { method: "POST", json: { finding_id: findingId } }),
  explainFlow: (id: string, symbolId: string, depth: number) =>
    request<ExplanationResponse>(`/api/analyses/${segment(id)}/explain/flow`, { method: "POST", json: { symbol_id: symbolId, depth } }),

  jiraStatus: () => request<JiraStatus>("/api/jira/status"),
  jiraConnect: (values: { site_url: string; email: string; api_token: string }) =>
    request<JiraStatus & { identity: { display_name: string | null; account_id: string | null } }>("/api/jira/connection", { method: "POST", json: values }),
  jiraDisconnect: () => request<JiraStatus>("/api/jira/connection", { method: "DELETE" }),
  jiraProjects: () => request<JiraProject[]>("/api/jira/projects"),
  jiraPreview: (values: { analysis_id: string; finding_id: string; project_key: string; issue_type: string }) =>
    request<JiraPreview>("/api/jira/tickets/preview", { method: "POST", json: values }),
  jiraCreate: (values: { analysis_id: string; finding_id: string; project_key: string; issue_type: string }) =>
    request<JiraTicketRecord>("/api/jira/tickets", { method: "POST", json: { ...values, confirm: true } }),
  jiraTickets: () => request<JiraTicketRecord[]>("/api/jira/tickets"),
  jiraIssueStatus: (key: string) => request<JiraIssueStatus>(`/api/jira/issues/${segment(key)}/status`),
  mcpStatus: () => request<McpStatus>("/api/mcp/status"),
  learningOverview: (id: string) => request<LearningOverview>(`/api/analyses/${segment(id)}/learning/overview`),
  learningGenerate: (id: string, body: { mode: string; difficulty?: string; module?: string; count?: number }) =>
    request<LearningBatch>(`/api/analyses/${segment(id)}/learning/questions`, { method: "POST", json: body }),
  learningHint: (id: string, questionId: string) =>
    request<{ hint: string }>(`/api/analyses/${segment(id)}/learning/questions/${segment(questionId)}/hint`, { method: "POST" }),
  learningAnswer: (id: string, questionId: string, body: { selected?: string[]; order?: string[] }) =>
    request<LearningAnswer>(`/api/analyses/${segment(id)}/learning/questions/${segment(questionId)}/answer`, { method: "POST", json: body }),
  learningProgress: (id: string) => request<LearningProgress>(`/api/analyses/${segment(id)}/learning/progress`),
  textSearch: (id: string, q: string) => request<{ query: string; results: TextHit[] }>(`/api/analyses/${segment(id)}/text-search${query({ q, limit: 200 })}`),
  importSearch: (id: string, q: string) => request<{ query: string; results: ImportHit[] }>(`/api/analyses/${segment(id)}/import-search${query({ q, limit: 200 })}`),
  conversations: (id: string) => request<ConversationSummary[]>(`/api/analyses/${segment(id)}/conversations`),
  createConversation: (id: string) => request<ConversationSummary>(`/api/analyses/${segment(id)}/conversations`, { method: "POST", json: {} }),
  conversationDetail: (id: string, conversationId: string) =>
    request<ConversationDetail>(`/api/analyses/${segment(id)}/conversations/${segment(conversationId)}`),
  deleteConversation: (id: string, conversationId: string) =>
    request<{ deleted: string }>(`/api/analyses/${segment(id)}/conversations/${segment(conversationId)}`, { method: "DELETE" }),
};

export async function streamConversation(
  analysisId: string,
  conversationId: string,
  question: string,
  mode: string,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/analyses/${segment(analysisId)}/conversations/${segment(conversationId)}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify({ question, mode }),
    });
  } catch {
    throw new ApiError("Cannot reach the RepoMind server. Check that it is running.", 0);
  }
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(errorMessage(payload, response.status), response.status);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as Record<string, unknown>);
      newline = buffer.indexOf("\n");
    }
  }
  const rest = buffer.trim();
  if (rest) onEvent(JSON.parse(rest) as Record<string, unknown>);
}

export type { ConversationMessage };
