export type Severity = "high" | "medium" | "low" | "info";
export type Confidence = "confirmed" | "approximate" | "external" | "unresolved" | "heuristic";

export interface AnalysisSummaryStats {
  python_files: number;
  total_lines: number;
  classes: number;
  functions: number;
  methods: number;
  imports: number;
  findings: number;
  parse_errors: number;
  module_dependencies: number;
  external_dependencies: number;
  call_relationships: number;
  circular_dependencies: number;
  findings_by_severity: Record<Severity, number>;
  findings_by_category: Record<string, number>;
  warnings: string[];
  language_coverage?: { analyzed: string[]; python_files: number; not_analyzed: Record<string, number> };
}

export interface AnalysisMeta {
  analysis_id: string;
  repository: string;
  source_type: "zip" | "github" | "local";
  source_ref: string;
  commit: string | null;
  created_at: string;
  summary: AnalysisSummaryStats;
  warnings: string[];
  has_report: boolean;
}

export interface DependencySummary {
  module_dependencies: number;
  external_dependencies: number;
  external_modules: Record<string, number>;
  call_relationships: number;
  confirmed_call_relationships: number;
  approximate_call_relationships: number;
  external_call_relationships: number;
  unresolved_call_relationships: number;
  contains_relationships: number;
  circular_dependencies: number;
  lazy_module_dependencies: number;
  hub_modules: { module: string; fan_in: number; fan_out: number }[];
  most_called_symbols: { id: string; name: string; confirmed_callers: number }[];
  unresolved_references: number;
}

export interface CycleInfo {
  modules: string[];
  example_cycle: string[];
  runtime_risk: string;
  note: string;
}

export interface ComplexFunction {
  id: string;
  qualname: string;
  file: string;
  line: number;
  complexity: number;
  length: number;
}

export interface LargeFile {
  path: string;
  lines: number;
  functions: number;
}

export interface Overview {
  analysis_id: string;
  repository: string;
  source_type: string;
  source_ref: string;
  commit: string | null;
  created_at: string;
  summary: AnalysisSummaryStats;
  warnings: string[];
  dependency_summary: DependencySummary;
  cycles: CycleInfo[];
  findings_summary: Record<string, number>;
  most_complex: ComplexFunction[];
  largest_files: LargeFile[];
}

export interface FileRow {
  path: string;
  module: string;
  lines: number;
  classes: number;
  functions: number;
  imports: number;
  findings: number;
  parse_error: { message: string; line: number } | null;
}

export interface ImportRecord {
  kind: "import" | "from";
  module: string;
  symbol: string | null;
  local: string;
  target: string | null;
  level: number;
  line: number;
  lazy: boolean;
}

export interface Finding {
  id: string;
  why_it_matters?: string;
  rule_id: string;
  legacy_rule?: string | null;
  title: string;
  category: string;
  severity: Severity;
  confidence: string;
  file: string;
  line: number;
  end_line: number;
  evidence: string;
  explanation: string;
  remediation: string;
  symbol_id: string | null;
}

export interface SymbolRow {
  id: string;
  file?: string;
  name: string;
  qualname: string;
  kind: "function" | "method" | "nested_function" | "class";
  line: number;
  end_line: number;
  is_async: boolean;
  complexity: number;
  length: number;
}

export interface FileDetail {
  path: string;
  module: string;
  is_package: boolean;
  lines: number;
  size_bytes: number;
  parse_error: { message: string; line: number } | null;
  imports: ImportRecord[];
  classes: {
    id: string;
    name: string;
    qualname: string;
    line: number;
    end_line: number;
    bases: string[];
    methods: { id: string; name: string; line: number; method_type: string; is_async: boolean; complexity: number }[];
  }[];
  symbols: SymbolRow[];
  findings: Finding[];
  module_dependencies: {
    imports: { module: string; line: number; lazy: boolean; names: string[] }[];
    imported_by: { module: string; line: number; lazy: boolean }[];
  };
}

export interface CallRef {
  target?: string | null;
  source?: string;
  source_name?: string;
  target_name?: string;
  file?: string | null;
  line: number;
  resolution: string;
  confidence: Confidence | string;
  candidates?: { id: string; name: string }[];
}

export interface SymbolDetail {
  id: string;
  name: string;
  qualname: string;
  kind: string;
  file: string;
  module: string;
  class_name: string | null;
  is_async: boolean;
  is_nested: boolean;
  method_type: string | null;
  line: number;
  end_line: number;
  length: number;
  complexity: number;
  decorators: string[];
  arguments: { name: string; annotation: string | null; default: boolean; kind: string }[];
  returns: string | null;
  docstring: string | null;
  bases: string[];
  source: { start_line: number; end_line: number; text: string; truncated: boolean };
  members: string[];
  callers: CallRef[];
  callees: CallRef[];
  findings: Finding[];
}

export interface GraphNode {
  id: string;
  label: string;
  file?: string;
  kind?: string;
  module?: string;
  line?: number;
  complexity?: number;
  fan_in?: number;
  fan_out?: number;
  functions?: number;
  classes?: number;
  in_cycle?: boolean;
  degree?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  confidence: string;
  lazy: boolean;
  names?: string[];
  line: number;
  label: string;
  resolution?: string;
  in_cycle?: boolean;
}

export interface DependencyGraph {
  scope: "modules" | "functions";
  confidence: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
}

export interface SearchHit {
  chunk_id: string;
  file: string;
  line: number;
  end_line: number;
  symbol: string | null;
  symbol_id: string | null;
  kind: string;
  score: number;
  matched_terms: string[];
  method: string;
  snippet: string;
}

export interface Reference {
  file: string;
  start_line: number;
  end_line: number;
  label?: string | null;
  symbol_id?: string | null;
}

export interface AskResponse {
  question: string;
  answer: string;
  mode: "llm" | "deterministic" | "insufficient-evidence";
  ai_status: string;
  model: string | null;
  insufficient_evidence: boolean;
  citations: Reference[];
  uncited: boolean;
  evidence: SearchHit[];
  graph_facts: string[];
  retrieval: string;
  retrieval_note: string | null;
  references: Reference[];
}

export interface ExplanationResponse {
  text: string;
  mode: "llm" | "deterministic";
  ai_status: string;
  model: string | null;
  references: Reference[];
  cached?: boolean;
  flow?: { root: string; tree: FlowNode; lines: string[] };
}

export interface FlowNode {
  id: string;
  name: string;
  line: number | null;
  confidence: string | null;
  resolution: string | null;
  recursive: boolean;
  children: FlowNode[];
}

export interface RiskListResponse {
  total: number;
  summary: { total: number; by_severity: Record<string, number>; by_category: Record<string, number>; by_rule: Record<string, number> };
  findings: Finding[];
}

export interface JiraStatus {
  configured: boolean;
  source: "session" | "environment" | null;
  base_url: string | null;
  email: string | null;
  session_override_active: boolean;
}

export interface JiraProject {
  key: string;
  name: string;
  id: string;
  issue_types: string[];
}

export interface JiraPreview {
  project: string;
  issue_type: string;
  summary: string;
  labels: string[];
  description: string;
  finding_id: string;
  warnings: string[];
  analysis_id: string;
}

export interface JiraTicketRecord {
  id: number;
  analysis_id: string | null;
  finding_id: string | null;
  project_key: string;
  issue_key: string;
  issue_url: string;
  summary: string;
  created_at: string;
}

export interface JiraIssueStatus {
  key: string;
  summary: string | null;
  status: string | null;
  status_category: string | null;
  priority: string | null;
  assignee: string | null;
  updated: string | null;
  url: string;
}

export interface Preferences {
  default_risk_severity: Severity;
  graph_max_nodes: number;
  retrieval_mode: "lexical" | "hybrid";
  show_approximate_edges: boolean;
}

export interface AppConfig {
  version: string;
  ai_enabled: boolean;
  model: string;
  embedding_model: string;
  retrieval_mode: string;
  limits: {
    max_upload_mb: number;
    max_repository_mb: number;
    max_python_files: number;
    max_file_kb: number;
    clone_timeout_seconds: number;
  };
  jira: JiraStatus;
  mcp_tool_count: number;
}

export interface McpTool {
  name: string;
  description: string;
  parameters: { name: string; type: string; required: boolean; description: string }[];
}

export interface AIStatus {
  connected: boolean;
  source: "session" | "environment" | null;
  model: string;
  embedding_model: string;
}

export interface ConversationSummary {
  id: string;
  analysis_id: string;
  title: string;
  created_at: string;
  message_count?: number;
}

export interface ConversationMessage {
  id: number;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  mode: string | null;
  payload: {
    mode?: string;
    ai_status?: string;
    citations?: Reference[];
    suggestions?: string[];
    insufficient_evidence?: boolean;
    uncited?: boolean;
    explanation_mode?: string;
    retrieval?: string;
  } | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

export interface TextHit {
  file: string;
  line: number;
  text: string;
  symbol: string | null;
  symbol_id: string | null;
}

export interface ImportHit {
  file: string;
  line: number;
  statement: string;
  module: string;
  symbol: string | null;
}

export interface McpStatus {
  ready: boolean;
  tools_registered: number;
  tools_expected: number;
  missing: string[];
  launch_command: string[];
}

export interface LearningOption {
  id: string;
  text: string;
}

export interface LearningEvidence {
  file: string;
  start_line: number;
  end_line: number;
  label: string;
}

export interface LearningQuestion {
  id: string;
  mode: string;
  mode_label: string;
  difficulty: "beginner" | "intermediate" | "advanced";
  module: string | null;
  kind: "choice" | "order";
  prompt: string;
  excerpt: { file: string; start_line: number; text: string } | null;
  options: LearningOption[];
  source: string;
}

export interface LearningAnswer {
  question_id: string;
  already_answered: boolean;
  correct: boolean;
  points: number;
  matched_positions: number;
  your_answer: string[];
  correct_answer: string[];
  explanation: string;
  evidence: LearningEvidence[];
}

export interface LearningProgress {
  answered: number;
  correct: number;
  points: number;
  accuracy: number | null;
  generated: number;
  by_mode: Record<string, { answered: number; correct: number }>;
  review: {
    question_id: string;
    mode: string;
    mode_label: string;
    prompt: string;
    correct_answer: string[];
    explanation: string;
    evidence: LearningEvidence[];
  }[];
}

export interface LearningOverview {
  modes: { id: string; label: string }[];
  difficulties: string[];
  modules: string[];
  progress: LearningProgress;
}

export interface LearningBatch {
  questions: LearningQuestion[];
  available: number;
  reason: string | null;
  generator: string;
}
