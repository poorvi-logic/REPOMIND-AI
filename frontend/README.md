# RepoMind AI frontend

React 19, TypeScript, Vite 7, Tailwind CSS 4, Lucide icons, React Flow (`@xyflow/react`) with Dagre for graph
layout, and `prism-react-renderer` for Python syntax highlighting. All data comes from the RepoMind API. The UI contains no mock data.

## Scripts

```bash
npm install            # install dependencies (uses package-lock.json)
npm run dev            # Vite dev server on http://localhost:5173, proxies /api to http://127.0.0.1:8000
npm run typecheck      # TypeScript strict check (noUnusedLocals enabled)
npm run build          # type-check, then production build into dist/
npm run preview        # serve dist/ locally
```

Run the backend first (`uvicorn app.main:app --port 8000` from the project root). Once `dist/` exists, the backend
also serves the built interface at `http://127.0.0.1:8000/`, so the dev server is optional.

## Structure

```
src/
  App.tsx               route table (lazy-loaded pages)
  main.tsx              entry point, BrowserRouter
  index.css             Tailwind theme (navy/charcoal palette), React Flow overrides
  types.ts              response types mirroring the API
  lib/api.ts            typed fetch client with error extraction
  lib/hooks.ts          useAsync (loading, error, reload) and last-analysis memory
  lib/format.ts         severity and confidence styles, formatting
  components/Layout.tsx responsive sidebar and mobile navigation
  components/ui.tsx     cards, badges, stat tiles, alerts, buttons, form fields
  components/CodeView.tsx  highlighted source with line numbers and range highlighting
  pages/                Overview, Explorer, Intelligence, Dependencies, Risks, Assistant, MCP, Jira, Settings
```

## Behaviour notes

- Loading, empty and error states are shown on every data-driven view. Retry buttons re-run the request.
- AI output always shows its mode: `AI model`, `Deterministic · No API key`, `Insufficient evidence` or the error status.
- Jira creation requires a preview followed by an explicit confirmation checkbox.
- Credentials are never stored in the browser. The Jira form posts them once to the server, which keeps them in memory.
