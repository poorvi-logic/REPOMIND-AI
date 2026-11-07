# RepoMind AI API examples

Base URL: `http://127.0.0.1:8000`. Interactive documentation is at `/docs` (Swagger UI) and `/redoc`.
Replace `ANALYSIS_ID` with the `analysis_id` returned by an analysis request.

## Health and configuration

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/meta/config
```

## Analyze a repository

```bash
# ZIP archive
curl -F "file=@my-project.zip" http://127.0.0.1:8000/api/analyses/upload

# Public GitHub repository (shallow clone)
curl -X POST http://127.0.0.1:8000/api/analyses/github \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/pallets/itsdangerous"}'

# History and metadata
curl http://127.0.0.1:8000/api/analyses
curl http://127.0.0.1:8000/api/analyses/ANALYSIS_ID
```

## Explore files and symbols

```bash
curl http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/files
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/file?path=orders.py"
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/source?path=payment.py"
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/symbols?q=refund&kind=method"
# Symbol ids look like "orders.py::OrderService.refund" (the id is used as a path suffix)
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/symbols/orders.py::OrderService.refund"
```

## Dependencies

```bash
# Module graph for React Flow (nodes and edges)
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/dependencies?scope=modules"
# Function graph including approximate name-based links
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/dependencies?scope=functions&confidence=all&max_nodes=80"
curl http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/dependencies/summary
curl http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/modules/orders/dependencies
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/call-flow?symbol_id=main.py::main&depth=3"
```

## Risk findings

```bash
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/risks?min_severity=medium"
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/risks/FINDING_ID"
```

## Search and questions

```bash
curl "http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/search?q=payment%20validation"
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Where is payment validation implemented?"}'
```

The answer includes `mode` (`llm`, `deterministic` or `insufficient-evidence`), `ai_status`, `citations`
with file and line references, and `graph_facts`.

## AI explanations

```bash
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/explain/file \
  -H "Content-Type: application/json" -d '{"path": "payment.py"}'
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/explain/symbol \
  -H "Content-Type: application/json" -d '{"symbol_id": "main.py::checkout"}'
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/explain/architecture
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/explain/module \
  -H "Content-Type: application/json" -d '{"module": "orders"}'
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/explain/finding \
  -H "Content-Type: application/json" -d '{"finding_id": "FINDING_ID"}'
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/explain/flow \
  -H "Content-Type: application/json" -d '{"symbol_id": "main.py::main", "depth": 2}'
```

## Reports

```bash
curl -X POST http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/report
curl -o repomind-report.json http://127.0.0.1:8000/api/analyses/ANALYSIS_ID/report/download
```

## Jira

```bash
# Validate and store session credentials in server memory (never persisted, never returned)
curl -X POST http://127.0.0.1:8000/api/jira/connection \
  -H "Content-Type: application/json" \
  -d '{"site_url": "https://your-team.atlassian.net", "email": "you@example.com", "api_token": "YOUR_TOKEN"}'

curl http://127.0.0.1:8000/api/jira/projects

# Preview first (creates nothing)
curl -X POST http://127.0.0.1:8000/api/jira/tickets/preview \
  -H "Content-Type: application/json" \
  -d '{"analysis_id": "ANALYSIS_ID", "finding_id": "FINDING_ID", "project_key": "OPS", "issue_type": "Task"}'

# Create only after confirmation
curl -X POST http://127.0.0.1:8000/api/jira/tickets \
  -H "Content-Type: application/json" \
  -d '{"analysis_id": "ANALYSIS_ID", "finding_id": "FINDING_ID", "project_key": "OPS", "issue_type": "Task", "confirm": true}'

curl http://127.0.0.1:8000/api/jira/issues/OPS-123/status
curl http://127.0.0.1:8000/api/jira/tickets
```

## AI key

```bash
curl http://127.0.0.1:8000/api/ai/status
curl -X POST http://127.0.0.1:8000/api/ai/connection \
  -H "Content-Type: application/json" -d '{"api_key": "YOUR_OPENAI_KEY"}'
curl -X DELETE http://127.0.0.1:8000/api/ai/connection
```

The key is validated with one request to OpenAI, kept in server memory, and never returned by the API.

## Settings and MCP catalogue

```bash
curl http://127.0.0.1:8000/api/settings
curl -X PUT http://127.0.0.1:8000/api/settings \
  -H "Content-Type: application/json" -d '{"graph_max_nodes": 200, "retrieval_mode": "lexical"}'
curl http://127.0.0.1:8000/api/mcp/tools
curl http://127.0.0.1:8000/api/mcp/config
```

## Assistant conversations

```bash
# Start a conversation (title is optional; it is set from the first question if omitted)
curl -X POST http://127.0.0.1:8000/api/analyses/$ID/conversations -H "Content-Type: application/json" -d '{}'

# Ask and wait for the full answer. mode is beginner, developer or deep_dive
curl -X POST http://127.0.0.1:8000/api/analyses/$ID/conversations/$CID/messages \
  -H "Content-Type: application/json" -d '{"question":"Where is payment validated?","mode":"beginner"}'

# Stream the answer as NDJSON lines: context, delta (text pieces), then done
curl -N -X POST http://127.0.0.1:8000/api/analyses/$ID/conversations/$CID/stream \
  -H "Content-Type: application/json" -d '{"question":"And what does it return?","mode":"developer"}'
```

## Explorer search

```bash
curl "http://127.0.0.1:8000/api/analyses/$ID/text-search?q=payment&limit=50"
curl "http://127.0.0.1:8000/api/analyses/$ID/import-search?q=orders"
```

## CodeQuest

```bash
curl http://127.0.0.1:8000/api/analyses/$ID/learning/overview
curl -X POST http://127.0.0.1:8000/api/analyses/$ID/learning/questions \
  -H "Content-Type: application/json" -d '{"mode":"mixed","difficulty":"beginner","count":5}'
# Questions come back without their answers. Choice questions take one option id
curl -X POST http://127.0.0.1:8000/api/analyses/$ID/learning/questions/$QID/answer \
  -H "Content-Type: application/json" -d '{"selected":["o1"]}'
# Workflow questions take every option id once, in the order you chose
curl -X POST http://127.0.0.1:8000/api/analyses/$ID/learning/questions/$QID/answer \
  -H "Content-Type: application/json" -d '{"order":["o2","o0","o1"]}'
curl -X POST http://127.0.0.1:8000/api/analyses/$ID/learning/questions/$QID/hint
curl http://127.0.0.1:8000/api/analyses/$ID/learning/progress
```

## MCP readiness

```bash
curl http://127.0.0.1:8000/api/mcp/status
```

## Legacy endpoints (original starter API)

These operate on the most recent analysis: `POST /api/analyze/upload`, `GET /api/report/latest`,
`GET /api/report/download`, `GET /api/search?q=`, `POST /api/ask`, `GET /api/explain/{file_path}`,
and `POST /api/ticket-draft` with `{"finding_index": 0}`.
