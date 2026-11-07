import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { Plus, Send, Trash2 } from "lucide-react";
import { api, streamConversation } from "../lib/api";
import { errorText, formatDate } from "../lib/format";
import { rememberAnalysis, useAsync } from "../lib/hooks";
import type { ConversationMessage, Reference } from "../types";
import { Button, EmptyState, ErrorAlert, LoadingBlock, SourceBadge, cx, inputClass } from "../components/ui";

type Mode = "beginner" | "developer" | "deep_dive";

const MODES: { id: Mode; label: string }[] = [
  { id: "beginner", label: "Beginner" },
  { id: "developer", label: "Developer" },
  { id: "deep_dive", label: "Deep dive" },
];

interface Turn {
  key: string;
  role: "user" | "assistant";
  content: string;
  citations: Reference[];
  mode?: string;
  aiStatus?: string;
  pending?: boolean;
  error?: string;
}

function fromMessage(message: ConversationMessage): Turn {
  return {
    key: `m${message.id}`,
    role: message.role,
    content: message.content,
    citations: message.payload?.citations ?? [],
    mode: message.payload?.mode,
    aiStatus: message.payload?.ai_status,
  };
}

export function AssistantPage() {
  const { analysisId = "" } = useParams();
  const overview = useAsync(() => api.overview(analysisId), [analysisId]);
  const conversations = useAsync(() => api.conversations(analysisId), [analysisId]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<Mode>("developer");
  const [sending, setSending] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const counter = useRef(0);

  useEffect(() => {
    rememberAnalysis(analysisId);
    setActiveId(null);
    setTurns([]);
    setSuggestions([]);
  }, [analysisId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const starters = useMemo(() => {
    const list: string[] = [];
    const topFunction = overview.data?.dependency_summary.most_called_symbols[0];
    if (topFunction) list.push(`What does ${topFunction.name} do?`);
    const hub = overview.data?.dependency_summary.hub_modules[0];
    if (hub) list.push(`What depends on ${hub.module}?`);
    list.push("Explain the structure of this project.");
    return list;
  }, [overview.data]);

  async function openConversation(id: string) {
    setActiveId(id);
    setLoadingThread(true);
    setError(null);
    setSuggestions([]);
    try {
      const detail = await api.conversationDetail(analysisId, id);
      setTurns(detail.messages.map(fromMessage));
      const lastAnswer = [...detail.messages].reverse().find((item) => item.role === "assistant");
      setSuggestions(lastAnswer?.payload?.suggestions ?? []);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setLoadingThread(false);
    }
  }

  function startNew() {
    setActiveId(null);
    setTurns([]);
    setSuggestions([]);
    setError(null);
  }

  async function removeConversation(id: string) {
    try {
      await api.deleteConversation(analysisId, id);
      if (activeId === id) startNew();
      conversations.reload();
    } catch (caught) {
      setError(errorText(caught));
    }
  }

  async function send(question: string) {
    const text = question.trim();
    if (!text || sending) return;
    setError(null);
    let conversationId = activeId;
    if (!conversationId) {
      try {
        const created = await api.createConversation(analysisId);
        conversationId = created.id;
        setActiveId(created.id);
      } catch (caught) {
        setError(errorText(caught));
        return;
      }
    }
    const userKey = `u${counter.current++}`;
    const answerKey = `a${counter.current++}`;
    setTurns((current) => [
      ...current,
      { key: userKey, role: "user", content: text, citations: [] },
      { key: answerKey, role: "assistant", content: "", citations: [], pending: true },
    ]);
    setDraft("");
    setSending(true);
    setSuggestions([]);
    try {
      await streamConversation(analysisId, conversationId, text, mode, (event) => {
        if (event.type === "context") {
          const citations = (event.citations as Reference[]) ?? [];
          setTurns((current) => current.map((turn) => (turn.key === answerKey ? { ...turn, citations } : turn)));
        } else if (event.type === "delta") {
          const piece = String(event.text ?? "");
          setTurns((current) => current.map((turn) => (turn.key === answerKey ? { ...turn, content: turn.content + piece } : turn)));
        } else if (event.type === "done") {
          const message = event.message as ConversationMessage;
          setSuggestions((event.suggestions as string[]) ?? []);
          setTurns((current) =>
            current.map((turn) =>
              turn.key === answerKey
                ? {
                    ...turn,
                    pending: false,
                    content: message.content,
                    citations: message.payload?.citations ?? turn.citations,
                    mode: message.payload?.mode,
                    aiStatus: message.payload?.ai_status,
                  }
                : turn,
            ),
          );
        }
      });
    } catch (caught) {
      setTurns((current) => current.map((turn) => (turn.key === answerKey ? { ...turn, pending: false, error: errorText(caught) } : turn)));
    } finally {
      setSending(false);
      conversations.reload();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(draft);
    }
  }

  const shownSuggestions = turns.length === 0 ? starters : suggestions;

  return (
    <div className="grid gap-5 lg:grid-cols-[230px_minmax(0,1fr)]">
      <aside className="space-y-3">
        <Button variant="secondary" icon={Plus} className="w-full" onClick={startNew}>New conversation</Button>
        {conversations.loading && <LoadingBlock />}
        {conversations.error && <ErrorAlert message={conversations.error} onRetry={conversations.reload} />}
        {conversations.data && conversations.data.length === 0 && <p className="px-1 text-sm text-ink-500">No conversations yet.</p>}
        <ul className="space-y-1">
          {conversations.data?.map((item) => (
            <li key={item.id} className={cx("group flex items-center gap-1 rounded-lg", activeId === item.id ? "bg-navy-800" : "hover:bg-navy-850")}>
              <button type="button" onClick={() => void openConversation(item.id)} className="min-w-0 flex-1 px-3 py-2 text-left">
                <span className="block truncate text-sm text-ink-100">{item.title}</span>
                <span className="block text-[11px] text-ink-500">{formatDate(item.created_at)}</span>
              </button>
              <button type="button" aria-label="Delete conversation" onClick={() => void removeConversation(item.id)} className="mr-2 rounded-md p-1.5 text-ink-500 opacity-0 hover:text-rose-300 group-hover:opacity-100">
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex min-h-[70vh] flex-col">
        <div className="mb-4 flex justify-end">
          <div className="flex rounded-lg border border-navy-600 bg-navy-900 p-0.5">
            {MODES.map((item) => (
              <button key={item.id} type="button" onClick={() => setMode(item.id)} className={cx("rounded-md px-3 py-1.5 text-xs", mode === item.id ? "bg-navy-700 text-ink-50" : "text-ink-400 hover:text-ink-100")}>
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 space-y-6 pb-6">
          {loadingThread && <LoadingBlock label="Loading conversation" />}
          {error && <ErrorAlert message={error} />}
          {turns.length === 0 && !loadingThread && (
            <EmptyState icon={Plus} title="Ask anything about this project." />
          )}
          {turns.map((turn) => (
            <div key={turn.key} className={cx("flex", turn.role === "user" && "justify-end")}>
              {turn.role === "user" && (
                <p className="max-w-[78%] rounded-xl bg-navy-800 px-4 py-2.5 text-sm text-ink-100">{turn.content}</p>
              )}
              {turn.role === "assistant" && (
                <div className="w-full max-w-[880px] space-y-3">
                  {turn.mode && turn.aiStatus && <SourceBadge mode={turn.mode} status={turn.aiStatus} />}
                  {turn.pending && !turn.content && <LoadingBlock label="Searching the project" />}
                  {turn.content && <p className="whitespace-pre-wrap text-sm leading-7 text-ink-200">{turn.content}</p>}
                  {turn.error && <ErrorAlert message={turn.error} />}
                  {turn.citations.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {turn.citations.map((citation) => (
                        <Link
                          key={`${citation.file}-${citation.start_line}`}
                          to={`/analyses/${analysisId}/explorer?path=${encodeURIComponent(citation.file)}&line=${citation.start_line}`}
                          className="rounded-md border border-navy-600 px-2.5 py-1 text-xs text-ink-300 hover:border-accent/50 hover:text-ink-100"
                        >
                          {citation.file}, line {citation.start_line}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {shownSuggestions.length > 0 && !sending && (
            <div className="flex flex-wrap gap-2">
              {shownSuggestions.map((suggestion) => (
                <button key={suggestion} type="button" onClick={() => void send(suggestion)} className="rounded-full border border-navy-600 px-3.5 py-2 text-sm text-ink-300 hover:border-accent/50 hover:text-ink-100">
                  {suggestion}
                </button>
              ))}
            </div>
          )}
          <div ref={endRef} />
        </div>

        <form onSubmit={submit} className="sticky bottom-0 border-t border-navy-700 bg-navy-950/90 pt-4 backdrop-blur">
          <label htmlFor="assistant-input" className="sr-only">Question</label>
          <div className="flex items-end gap-3 rounded-xl border border-navy-600 bg-navy-900 p-2 focus-within:border-accent/50">
            <textarea
              id="assistant-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              maxLength={2000}
              placeholder="Ask about this project"
              className={cx(inputClass, "min-h-[40px] flex-1 resize-none border-0 bg-transparent focus:ring-0")}
            />
            <Button type="submit" icon={Send} loading={sending} disabled={!draft.trim()}>Send</Button>
          </div>
        </form>
      </section>
    </div>
  );
}
