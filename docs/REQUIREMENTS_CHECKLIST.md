# Requirements checklist

This checklist compares the two original specifications with the delivered code. It uses four statuses:

- **Fully implemented and tested**: the behaviour is in the code and an automated test or a headless-browser run covers it.
- **Partially implemented**: part of the requirement exists; the rest is missing or only approximated. The note says which part.
- **Not implemented**: no working code for this requirement.
- **Implemented but not tested**: the code exists, but no test or browser run checks it. Where a test uses a fake or mocked service, the entry says so; a fake is not a live integration.

Test counts are from the final run recorded in `docs/FEATURE_STATUS.md`.

## Specification 1: RepoMind AI development

### 1. Audit

| Requirement | Status | Notes |
|---|---|---|
| Inspect code, architecture, storage, AST, dependencies, LLM, MCP, tests; keep an internal feature audit | Fully implemented and tested | Audit findings are recorded in this file and in `docs/FEATURE_STATUS.md`. |

### 2. Core product purpose

| Requirement | Status | Notes |
|---|---|---|
| Understand unfamiliar repositories, explore source, trace dependencies, find risks, ask grounded questions, expose tools to AI agents | Partially implemented | All of these exist. Several sub-features listed below are partial or missing. |

### 3. Remove hardcoded and duplicated behaviour

| Requirement | Status | Notes |
|---|---|---|
| Metrics, findings, relationships and MCP status are calculated from the analysed repository | Fully implemented and tested | No hardcoded metrics or findings were found. MCP readiness is checked in-process at request time. |
| Shared backend services used by API, MCP and CLI | Fully implemented and tested | `AppServices`, `RepositoryIndex` and `McpToolkit` are shared. |

### 4. Repository explorer

| Requirement | Status | Notes |
|---|---|---|
| File browsing | Implemented but not tested | Page loads in the browser run; no automated UI test. |
| Filename search | Implemented but not tested | Client-side filter over the file tree. |
| Function-name search | Implemented but not tested | Backend `/symbols` search is tested; the Explorer control was not clicked in a browser run. |
| Class-name search | Implemented but not tested | Same search as function names; classes are included. |
| Full-text source search across the whole repository | Fully implemented and tested | Backend tests; browser run returned matches. |
| Import search | Fully implemented and tested | Backend tests; browser run found an import. |
| Navigation between related files | Partially implemented | Import lists link to files. There is no dedicated related-file navigation. |
| Syntax-highlighted source with line numbers | Implemented but not tested | Prism-based viewer; no automated check of line-number rendering. |
| Function and class selection | Implemented but not tested | Present in the Explorer; not separately browser-tested. |
| Clickable references to source locations | Fully implemented and tested | Assistant citations and CodeQuest evidence links were clicked in browser runs. |
| Search covers the whole indexed repository, not the displayed files | Fully implemented and tested | Server-side search over all indexed files. |
| Arbitrary Python project structures | Partially implemented | `src/` layout and nested packages are tested; there is no broad test matrix. |
| Report coverage for unsupported languages | Fully implemented and tested | Overview lists Python as analysed and counts other file types as not analysed. |

### 5. Intelligent summarisation

| Requirement | Status | Notes |
|---|---|---|
| File, function, class and project summaries | Implemented but not tested | Deterministic fallbacks are tested. The AI path is tested with a mocked model only. |
| Eight-point explanation structure | Implemented but not tested | The structure is requested in the prompt. Output quality with a real model was not checked. |
| Grounded examples, marked illustrative, no invented business rules | Implemented but not tested | Prompt instruction only. |
| Project summary covers architecture and purpose | Implemented but not tested | Prompt plus deterministic architecture facts. Business purpose is generated only when the code makes it clear, and this was not checked against a real model. |

### 6. Code intelligence

| Requirement | Status | Notes |
|---|---|---|
| Summarise file, explain function, explain class, explain project | Implemented but not tested | Deterministic and mocked-model paths are tested. Live model not run. |
| Trace function calls, identify callers and callees | Fully implemented and tested | Call edges with confirmed and name-based labels. |
| Explain control flow | Partially implemented | Calls are listed in line order. Branches and loops are not modelled. |
| Identify parameters and return values | Fully implemented and tested | Extractor tests cover arguments and returns. |
| Identify exception handling | Partially implemented | Broad and bare `except` detection exists. There is no per-function map of which exceptions are raised or caught. |
| Explain important conditional branches | Partially implemented | Complexity counts only. |
| Source references with file paths and line numbers | Fully implemented and tested | |
| Do not confuse textual similarity with a confirmed call | Fully implemented and tested | Confidence labels and tests. |
| Label uncertain relationships | Fully implemented and tested | |

### 7. AI assistant

| Requirement | Status | Notes |
|---|---|---|
| Use the configured provider and model from Settings | Implemented but not tested | Fake and mocked clients in tests. Not run against the OpenAI API. |
| RAG: question, retrieval, prompt, model, references | Fully implemented and tested | Retrieval, prompt and citation tests. |
| Never fabricate; say when evidence is insufficient | Fully implemented and tested | Insufficient-evidence path never calls the model; tested. |
| Conversation history per project | Fully implemented and tested | Backend tests and browser run. |
| Context retained within a conversation | Fully implemented and tested | Test checks that the follow-up prompt contains the earlier question. |
| Streaming responses | Implemented but not tested | Backend streaming tested with a fake client; browser run covered the deterministic path. Live streaming not run. |
| Suggested follow-up questions | Fully implemented and tested | Derived from cited functions; browser run showed them. |
| Clickable source references | Fully implemented and tested | Browser run. |
| Code snippets with syntax highlighting in answers | Not implemented | Answers are plain text. |
| Beginner, Developer and Deep dive modes | Implemented but not tested | Mode instructions are tested in the prompt. Output quality was not checked with a real model. |
| File-specific and function-specific questions | Partially implemented | Handled by free-text retrieval. There is no file or function picker. |
| Architecture, debugging and code-review questions | Partially implemented | Handled by free-text retrieval. There are no dedicated modes. |
| Natural, professional tone | Implemented but not tested | Prompt instruction only. |

### 8. Risk analysis

| Requirement | Status | Notes |
|---|---|---|
| Hardcoded secrets (value redacted) | Fully implemented and tested | |
| Unsafe SQL construction | Fully implemented and tested | Inline SQL strings only. Variables built first are not detected (listed in limitations). |
| Potential injection risks | Partially implemented | Shell, `eval`/`exec` and unsafe deserialisation are checked. There is no taint analysis. |
| Unsafe file operations | Fully implemented and tested | |
| Missing input validation | Not implemented | |
| Broad exception handling | Fully implemented and tested | |
| Unhandled exceptions where detectable | Not implemented | |
| High cyclomatic complexity | Fully implemented and tested | |
| Excessive function length | Fully implemented and tested | |
| Duplicate code | Partially implemented | Exact matches of function bodies only. Near-duplicates are not detected. |
| Circular dependencies | Fully implemented and tested | |
| Potentially unused functions | Partially implemented | Name-based: a function is flagged only if its name appears nowhere else. This can miss unused functions and can flag functions used under a different name. |
| Risky subprocess execution | Fully implemented and tested | |
| Finding fields: ID, severity, category, file, line, evidence, explanation, why it matters, remediation, confidence | Partially implemented | Every field is present. Confidence is a single label ("heuristic"), not graded levels. |
| Avoid repetitive findings and group related ones | Implemented but not tested | Grouped by rule on the Risk page. |
| Filtering and searching findings | Implemented but not tested | Controls exist; not browser-tested. |
| Distinguish no issues, not performed, unsupported and failed | Partially implemented | "No issues" message and unsupported-coverage notes exist. "Not performed" is not a separate state. |

### 9. Dependency graph and visual explanations

| Requirement | Status | Notes |
|---|---|---|
| Module-level dependency graph | Fully implemented and tested | API tests and browser runs. |
| Function-level call graph | Fully implemented and tested | API tests; earlier browser run. |
| Class relationship graph | Not implemented | Class containment exists in the data, but there is no class graph view. |
| Repository architecture graph | Fully implemented and tested | Module graph. |
| Selected-function execution flow | Implemented but not tested | Call-flow API exists and the Intelligence page shows it. Not browser-tested. |
| Click nodes to inspect | Fully implemented and tested | Earlier browser run. |
| Open source files from a node | Partially implemented | Node details link to the Explorer; no automated check. |
| Highlight incoming and outgoing dependencies | Not implemented | |
| Search graph nodes | Implemented but not tested | |
| Filter relationships | Implemented but not tested | |
| Navigate to callers and callees | Partially implemented | Lists in the detail panel; no graph-level navigation. |
| Avoid dense graphs; progressive expansion | Fully implemented and tested | Default 14 connected modules and a "Show all" option. |
| No fabricated relationships | Fully implemented and tested | Relationships come from the AST and carry confidence labels. |

### 10. MCP server

| Requirement | Status | Notes |
|---|---|---|
| Real MCP SDK, not a static catalogue | Fully implemented and tested | Official `mcp` package. |
| Eight tools backed by the application's services | Fully implemented and tested | All eight are tested in-process. Only `scan_repository` was invoked through a real stdio client in automated tests. |
| Validated input, structured results, handled errors | Fully implemented and tested | |
| Identify the relevant project; respect isolation | Partially implemented | Analyses are addressed by ID, and an optional directory allow-list exists. There is no authentication per client. |
| Client configuration instructions | Implemented but not tested | Documented in README section 12. Not tested in a desktop MCP client. |
| Test discovery and invocation with a real client | Fully implemented and tested | Stdio session lists tools and calls `scan_repository`. |
| Tool status from actual availability | Partially implemented | `/api/mcp/status` checks that tools are registered in the server process. It does not confirm that a client can connect. |

### 11. Jira integration

| Requirement | Status | Notes |
|---|---|---|
| Connection validation | Implemented but not tested | Mocked HTTP only. |
| Secure credential storage | Implemented but not tested | Credentials are kept in memory only, never persisted or returned. Not checked against a real site. |
| Connection status | Implemented but not tested | Mocked HTTP. |
| Finding-to-ticket conversion (Atlassian Document Format) | Implemented but not tested | Mocked HTTP. |
| Ticket preview | Implemented but not tested | |
| Explicit user confirmation before creation | Fully implemented and tested | The API rejects creation without confirmation. |
| Ticket ID and URL after creation | Implemented but not tested | Mocked HTTP. |
| Error handling | Implemented but not tested | Mocked HTTP error mapping. |

### 12. Overview dashboard

| Requirement | Status | Notes |
|---|---|---|
| Number of source files | Fully implemented and tested | |
| Supported language coverage | Fully implemented and tested | |
| Number of classes and functions | Fully implemented and tested | |
| Module count | Partially implemented | Available in the dependency summary; not shown on the Overview page. |
| Dependency count | Partially implemented | Same as module count. |
| Risk findings by severity | Partially implemented | Overview shows total and high-severity counts. The full breakdown is on the Risk page. |
| Most complex functions | Fully implemented and tested | |
| Largest files | Fully implemented and tested | |
| Analysis completion status | Partially implemented | Analysis date and commit are shown. Analyses run synchronously, so there is no separate in-progress state. |
| No decorative charts | Fully implemented and tested | No chart library is used. |

### 13. Large and arbitrary ZIP support

| Requirement | Status | Notes |
|---|---|---|
| Arbitrary valid ZIP repositories | Fully implemented and tested | |
| Multiple independent projects | Fully implemented and tested | Project switcher; isolation test. |
| Configurable upload limits | Fully implemented and tested | `.env` settings. |
| 500 MB default upload limit | Fully implemented and tested | |
| Handle archives incrementally | Partially implemented | Upload is streamed to disk. Extraction and analysis are not incremental, and results are held in memory. |
| Exclude `.git`, `.venv`, `node_modules`, `build`, `dist` | Fully implemented and tested | Ingestion test. |
| Prevent path traversal | Fully implemented and tested | |
| Protect against ZIP bombs | Partially implemented | Expanded-size and file-count limits are enforced while extracting, and tested. There is no compression-ratio check. |
| Enforce expanded-size and file-count limits | Fully implemented and tested | Ingestion tests. |
| Handle corrupted archives gracefully | Fully implemented and tested | |
| Never execute uploaded source | Implemented but not tested | Analysis uses `ast.parse` only. No test asserts that code is never executed. |
| Maintain project isolation | Fully implemented and tested | Conversation and CodeQuest isolation tests. |
| Communicate actual limits | Implemented but not tested | Partial-analysis warnings and settings display exist. |

### 14. User interface and writing style

| Requirement | Status | Notes |
|---|---|---|
| Professional dark interface, consistent across pages | Implemented but not tested | Pages were loaded and screenshotted in headless Chromium. No visual regression tests. |
| Clear purpose per page; no repeated explanations | Implemented but not tested | Reviewed by reading the copy. |

### 15. Security

| Requirement | Status | Notes |
|---|---|---|
| No API keys in frontend code | Fully implemented and tested | Session keys are never returned by the API. |
| No secrets in source files | Fully implemented and tested | Scanned the project for credential-like strings; none found. |
| Server-side configuration | Fully implemented and tested | |
| Prevent cross-project data access | Fully implemented and tested | Isolation tests for conversations and CodeQuest. |
| Validate user input | Fully implemented and tested | Request models and path patterns; invalid input returns 422. |
| Handle uploaded ZIPs safely | Fully implemented and tested | |
| Do not execute uploaded code | Implemented but not tested | See section 13. |
| Protect sensitive content | Partially implemented | Secrets are redacted in findings. Source text is stored locally and shown in the Explorer (documented). |
| Avoid logging API keys and secrets | Implemented but not tested | Code review only. |

### 16. Testing

| Requirement | Status | Notes |
|---|---|---|
| ZIP extraction | Fully implemented and tested | |
| Repository indexing | Fully implemented and tested | |
| AST extraction, class and function detection | Fully implemented and tested | |
| Full-text search | Fully implemented and tested | |
| Dependency extraction and call tracing | Fully implemented and tested | |
| Risk detection | Fully implemented and tested | |
| Risk filtering | Implemented but not tested | |
| Summarisation | Implemented but not tested | Deterministic and mocked-model tests; no live model. |
| RAG retrieval and LLM response handling | Fully implemented and tested | Fake and mocked clients. |
| MCP server startup, tool discovery, tool invocation | Fully implemented and tested | Stdio session for discovery and one invocation; in-process tests for all eight tools. |
| Project isolation | Partially implemented | Tested for conversations and CodeQuest. Not separately tested for every Explorer route. |
| Jira connection handling | Implemented but not tested | Mocked HTTP only. |
| College Fee Management repository tests (student and programme relationships, fee plans, invoices, payments, partial payments, overpayment rejection, adjustments, refunds, database interactions) | Not implemented | The repository was not provided, so these tests were not written. |
| At least one different repository structure | Fully implemented and tested | `src/` layout test and a nested-package repository in CodeQuest tests. |

### 17. Deliverables

| Requirement | Status | Notes |
|---|---|---|
| Complete updated source ZIP | Fully implemented and tested | `RepoMind_AI_Final.zip`, verified from a clean extraction. |
| Updated requirements file | Fully implemented and tested | `requirements.txt` with minimum versions, not exact pins. |
| Environment variable example without secrets | Fully implemented and tested | `.env.example`, checked against every variable the code reads. |
| Setup instructions | Partially implemented | README covers installation. Tested on Linux only; Windows steps are from the README, not run on Windows. |
| README | Fully implemented and tested | |
| Architecture documentation | Fully implemented and tested | README sections 4 and 6. |
| MCP client configuration | Implemented but not tested | See section 10. |
| Test results | Fully implemented and tested | See `docs/FEATURE_STATUS.md` and the final report. |
| Known limitations | Fully implemented and tested | README section 16 and `docs/FEATURE_STATUS.md`. |
| Feature-completion report | Fully implemented and tested | `docs/FEATURE_STATUS.md` and this file. |

## Specification 2: CodeQuest – Learn Your Codebase

### 1. Purpose

| Requirement | Status | Notes |
|---|---|---|
| Interactive challenges generated from the uploaded code and analysis | Fully implemented and tested | |
| No hardcoded questions, answers, filenames or workflows | Fully implemented and tested | Generated from analysis data; tests use two different repositories. |

### 2. Learning modes

| Requirement | Status | Notes |
|---|---|---|
| A. Architecture Detective: module relationships, dependencies, explanation | Fully implemented and tested | Generator tests; browser run; diagram highlights modules. |
| B. Function Detective: what a function does, what it calls, who uses it | Fully implemented and tested | Docstring, input-count, call and caller questions; class questions too. |
| C. Workflow Challenge: arrange steps in order | Fully implemented and tested | Order follows call-line numbers. Browser run used the flowchart. Calls inside a branch or loop may not run every time, and the explanation says so. |
| D. Bug Detective: evidence-backed findings with excerpts | Fully implemented and tested | Only six evidence-backed rules are used. |
| E. Dependency Challenge: impact of a change, confirmed relationships only | Fully implemented and tested | Exact import edges only. |
| F. Risk Detective: risk, impact and remediation | Partially implemented | Questions ask for the fix. Impact is given in the explanation, not asked as a separate question. |

### 3. Adaptive question generation

| Requirement | Status | Notes |
|---|---|---|
| Generated from source, AST, metadata, call and dependency data, risk findings | Fully implemented and tested | |
| Repository documentation (README and similar) | Not implemented | |
| Use the configured LLM when available | Partially implemented | An AI model can reword question text and explanations. Each rewrite must keep every name in backticks and the stored answer key is not changed. Question selection and answers are not AI-generated. |
| Clearly identify fallback questions; never pretend an LLM made them | Fully implemented and tested | Each question shows "built from this project's analysis data" or "worded with AI from this project's analysis data". |
| Every question traceable to source evidence | Fully implemented and tested | Automated test checks every generated question's file and line range. |
| Explain insufficient information instead of inventing an answer | Fully implemented and tested | Reason messages; tested for a repository with no three-call workflow and for a repository with no Python. |

### 4. Learning experience

| Requirement | Status | Notes |
|---|---|---|
| Beginner, intermediate and advanced levels | Implemented but not tested | Levels are assigned per question and filtered. Not tested for each level individually. |
| Hints | Fully implemented and tested | Hint use is recorded on the server. |
| Multiple-choice and ordering questions | Fully implemented and tested | Browser run for both. |
| Explanations after each answer | Fully implemented and tested | Browser run. |
| Score and progress tracking | Fully implemented and tested | Points: 1 for a correct answer, 0.5 with a hint, 0 otherwise. Tested. |
| Module-specific practice | Implemented but not tested | Module filter in the UI and generator; not tested with a module filter. |
| Review section for incorrect answers | Fully implemented and tested | Browser run showed the review list. |
| Do not reward guessing without understanding | Partially implemented | Hints reduce points. The learner is not required to explain an answer before scoring. |

### 5. Visual learning

| Requirement | Status | Notes |
|---|---|---|
| Simplified architecture or dependency diagram | Fully implemented and tested | Browser run; modules from the existing dependency data. |
| Workflow sequence or flowchart | Fully implemented and tested | Vertical flowchart; browser run. |
| Highlight relevant nodes and steps during each challenge | Fully implemented and tested | Highlighting appears after the answer is checked, so it does not give the answer away. |
| Reuse RepoMind analysis data | Fully implemented and tested | |

### 6. UI and integration

| Requirement | Status | Notes |
|---|---|---|
| Separate section in navigation | Fully implemented and tested | Browser run. |
| Clean, professional, responsive, consistent | Implemented but not tested | Screenshots reviewed. Responsive layout not tested at narrow widths. |
| Existing pages not cluttered | Implemented but not tested | Reviewed in code; no visual regression test. |
| Start a session for the selected repository | Fully implemented and tested | Browser run. |

### 7. Technical requirements

| Requirement | Status | Notes |
|---|---|---|
| Actual backend endpoints and frontend interactions; no static mockup | Fully implemented and tested | |
| No hardcoded project-specific questions | Fully implemented and tested | |
| Question generation separate from UI components | Fully implemented and tested | `app/learning/` holds generation, grading and service; the page only calls the API. |
| Answers validated against generated data | Fully implemented and tested | Answer keys are stored on the server and never sent to the browser before answering. |
| Progress per repository and session | Partially implemented | Progress is per repository. There is no separate session concept. |
| Handle empty repositories and unsupported languages | Fully implemented and tested | Tests cover both. |
| Avoid executing uploaded code | Implemented but not tested | Analysis uses `ast.parse`; see section 13 of specification 1. |
| Automated tests for generation, evidence, validation and fallback | Fully implemented and tested | `tests/test_codequest.py`. |

### 8. User experience and tone

| Requirement | Status | Notes |
|---|---|---|
| Calm, encouraging mentor tone; simple language; practical examples | Implemented but not tested | Reviewed by reading the copy. Practical examples are not generated for every question. |

### 9. Integration and verification

| Requirement | Status | Notes |
|---|---|---|
| Inspect and reuse existing services; do not duplicate AST, dependency or risk logic | Fully implemented and tested | Uses `RepositoryIndex` and the risk rule metadata. |
| Run the tests | Fully implemented and tested | See final report. |
| Test with the ClinicFlow sample repository | Not implemented | ClinicFlow was not provided. |
| Test with another repository of a different structure | Fully implemented and tested | Automated tests and a browser run on a small repository written for testing. Not a real third-party project. |
| Questions change when a different repository is uploaded | Fully implemented and tested | Test compares question sets for two repositories. |
| Every question traceable to real source evidence | Fully implemented and tested | Automated check across generated questions. |
| Report completed, incomplete and untested functionality honestly | Fully implemented and tested | This file and `docs/FEATURE_STATUS.md`. |
| Preserve all existing RepoMind functionality | Fully implemented and tested | Full backend suite passes; frontend builds. |

## Open items that need input

- The College Fee Management repository. It was not in any upload, so the fee-specific tests were not written.
- The ClinicFlow repository. It was not in any upload, so it was not tested.
