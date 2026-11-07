import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { api } from "../lib/api";
import { useAsync } from "../lib/hooks";
import { Badge, Button, Card, ErrorAlert, LoadingBlock, PageHeader } from "../components/ui";

export function McpPage() {
  const tools = useAsync(() => api.mcpTools(), []);
  const status = useAsync(() => api.mcpStatus(), []);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function copySetup() {
    setError(null);
    try {
      const config = await api.mcpConfig();
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("Could not copy the setup. Try again.");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="MCP Integration"
        actions={
          <>
            {status.data && <Badge tone={status.data.ready ? "emerald" : "rose"}>{status.data.ready ? "Server ready" : "Server not ready"}</Badge>}
            {tools.data && <Badge>{tools.data.length} tools</Badge>}
            <Button variant="secondary" icon={copied ? Check : Copy} onClick={() => void copySetup()}>
              {copied ? "Copied" : "Copy setup"}
            </Button>
          </>
        }
      />
      {error && <ErrorAlert message={error} />}
      {tools.loading && <LoadingBlock label="Loading tools" />}
      {tools.error && <ErrorAlert message={tools.error} onRetry={tools.reload} />}
      {tools.data && (
        <Card className="overflow-hidden p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-navy-700 text-xs text-ink-500">
              <tr>
                <th className="px-5 py-3 font-medium">Tool</th>
                <th className="px-5 py-3 font-medium">What it does</th>
                <th className="px-5 py-3 font-medium">Inputs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-700">
              {tools.data.map((tool) => (
                <tr key={tool.name} className="align-top">
                  <td className="px-5 py-4 font-mono text-xs text-accent">{tool.name}</td>
                  <td className="px-5 py-4 text-ink-300">{tool.description}</td>
                  <td className="px-5 py-4">
                    <div className="flex flex-wrap gap-1.5">
                      {tool.parameters.map((parameter) => (
                        <span key={parameter.name} className={parameter.required ? "rounded-md bg-navy-700 px-2 py-0.5 font-mono text-[11px] text-ink-100" : "rounded-md border border-navy-700 px-2 py-0.5 font-mono text-[11px] text-ink-400"}>
                          {parameter.name}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
