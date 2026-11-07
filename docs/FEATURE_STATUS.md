# Feature status

## Implemented and tested
- ZIP upload (500 MB default, configurable), extraction limits, path-traversal rejection, corrupted-archive handling.
- Repository indexing for Python projects, including `src/` layouts.
- AST extraction: classes, methods, nested functions, decorators, arguments, calls, complexity.
- Module and function dependency graphs, with exact and name-based links labelled.
- Risk checks, including duplicate function bodies and possibly unused functions; each finding carries a "why it matters" line.
- Language coverage: Python is analysed; other file types are counted and reported as not analysed.
- Project overview: most complex functions, largest files, notes and circular imports.
- Repository Explorer search: file names, function and class names, exact source text, and imports.
- AI Assistant: saved conversations per project, Beginner, Developer and Deep dive modes, follow-up history, streamed answers, file and line citations.
- Answer modes use the same retrieved evidence, so the facts stay the same across modes.
- MCP server: 8 tools, checked with a real MCP client over stdio; readiness endpoint reports whether every tool is registered.
- Jira: preview, confirmation, duplicate protection.
- CodeQuest: six practice modes, difficulty levels, hints (half points when used), explanations, evidence links, progress and a review list, module filter.
- CodeQuest class questions: class purpose from its docstring, and which class defines a method.
- CodeQuest workflow answers are shown as a flowchart.
- CodeQuest question wording can be rewritten by the configured AI. The rewrite must keep every name in backticks and the answer key stays unchanged; questions that fail the check keep their original wording, and each question says where its wording came from.

## Implemented, partly tested
- CodeQuest AI wording: tested with a fake model and the checks above. Not run against the live OpenAI API.
- CodeQuest on the second repository: tested in the browser on a small repository written for the test, not on a real project.
- OpenAI answers, explanations and streaming: tested with a fake client and in the browser without a key. Not run against the live OpenAI API.
- Hybrid (keyword and embedding) search: tested with a fake embedding client only.
- Jira: tested against mocked HTTP responses only.
- Streaming answers: the browser run confirmed text arrives and the final message is saved. Long answers were not stress-tested.

## Not implemented
- Class relationship graph (class containment exists in the data; there is no graph view).
- Highlighting of incoming and outgoing dependencies on the dependency graph.
- Code-snippet syntax highlighting inside assistant answers.
- Missing-input-validation risk check.
- College Fee Management repository tests (repository not provided).
- ClinicFlow repository tests (repository not provided).
- CodeQuest use of repository documentation (README files).
- Separate CodeQuest sessions. Progress is kept per repository.
- CodeQuest questions from README or other documentation files.
- Unhandled-exception and missing-input-validation risk checks.
- Non-Python language analysis.
- Authentication, multi-user access and a background job queue.

## Needs input from you
- The College Fee Management repository. It was not in any uploaded file, so fee-specific tests (payments, partial payments, refunds, fee plans) are not written.
- The ClinicFlow sample repository. It was not in any uploaded file, so it was not tested.
- An OpenAI API key, to test live AI answers, streaming and AI-written explanations.
- A Jira test site, to test ticket creation for real.
