import { useRef, useState } from "react";
import { API_BASE } from "./api";

type Source = { rank: number; source: string; title: string; score: number };
type Meta = {
  cache?: string;
  route?: string;
  provider?: string;
  similarity?: string;
  fallback?: string;
  degraded?: string;
};
type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  meta?: Meta;
};

const SUGGESTIONS = [
  "What is a Pod in Kubernetes?",
  "How do rolling updates work in a Deployment?",
  "What are the different Service types?",
];

export default function ChatView() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () =>
    requestAnimationFrame(() =>
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    );

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "" }]);
    scrollToBottom();

    try {
      const resp = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          handleEvent(buffer.slice(0, sep));
          buffer = buffer.slice(sep + 2);
        }
      }
    } catch (err) {
      appendToAssistant(`\n\n[error: ${(err as Error).message}]`);
    } finally {
      setBusy(false);
      scrollToBottom();
    }
  }

  function handleEvent(raw: string) {
    let event = "message";
    let data = "";
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    const payload = JSON.parse(data);
    if (event === "sources") setAssistantSources(payload.sources);
    else if (event === "token") appendToAssistant(payload.content);
    else if (event === "meta") setAssistantMeta(payload);
    else if (event === "error") appendToAssistant(`\n\n[error: ${payload.message}]`);
    scrollToBottom();
  }

  const appendToAssistant = (text: string) =>
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last?.role !== "assistant") return m;
      return [...m.slice(0, -1), { ...last, content: last.content + text }];
    });

  const setAssistantSources = (sources: Source[]) =>
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last?.role !== "assistant") return m;
      return [...m.slice(0, -1), { ...last, sources }];
    });

  const setAssistantMeta = (meta: Meta) =>
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last?.role !== "assistant") return m;
      return [...m.slice(0, -1), { ...last, meta }];
    });

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="mx-auto w-full max-w-3xl flex-1 space-y-5 overflow-y-auto px-4 py-8">
        {messages.length === 0 && (
          <div className="pt-14 text-center">
            <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-harbor-muted">
              berth clear — no traffic
            </div>
            <p className="mt-3 font-sans text-harbor-muted">
              Ask the harbor about the ingested Kubernetes corpus.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-sm border border-harbor-line bg-harbor-surface px-3 py-1.5 font-mono text-xs text-harbor-fg transition-colors hover:border-harbor-beacon hover:text-harbor-beacon"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="surface-in max-w-[80%] rounded-md border border-harbor-line bg-harbor-surface2 px-4 py-2.5">
                <span className="mr-2 font-mono text-harbor-beacon">▸</span>
                <span className="font-sans text-harbor-fg">{msg.content}</span>
              </div>
            </div>
          ) : (
            <div key={i} className="flex justify-start">
              <div className="surface-in w-full max-w-[92%] rounded-md border border-harbor-line border-l-2 border-l-harbor-beacon bg-harbor-surface">
                <div className="flex items-center gap-3 px-4 pt-2.5">
                  <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-harbor-muted">
                    harbor
                  </span>
                  <span className="tick-rule flex-1" />
                </div>

                <p className="whitespace-pre-wrap px-4 py-2.5 font-sans leading-relaxed text-harbor-fg">
                  {msg.content || (busy ? <span className="text-harbor-muted">receiving…</span> : "")}
                </p>

                {msg.meta && (msg.meta.cache || msg.meta.route) && (
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 px-4 pb-2.5 font-mono text-[11px]">
                    {msg.meta.cache && (
                      <span className="flex items-center gap-2">
                        <span
                          className="led"
                          style={{ background: msg.meta.cache === "hit" ? "var(--harbor-patina)" : "var(--harbor-beacon)" }}
                        />
                        <span className={msg.meta.cache === "hit" ? "text-harbor-patina" : "text-harbor-muted"}>
                          {msg.meta.cache === "hit"
                            ? `CACHE HIT${msg.meta.similarity ? ` · ${msg.meta.similarity}` : ""}`
                            : "CACHE MISS"}
                        </span>
                      </span>
                    )}
                    {msg.meta.route && (
                      <span className="text-harbor-muted">
                        ROUTE <span className="text-harbor-fg">▸ {msg.meta.route.toUpperCase()}</span>
                      </span>
                    )}
                    {msg.meta.provider && <span className="text-harbor-muted">{msg.meta.provider}</span>}
                    {msg.meta.fallback === "true" && (
                      <span className="flex items-center gap-2 text-harbor-coral">
                        <span className="led" style={{ background: "var(--harbor-coral)" }} />
                        FALLBACK
                      </span>
                    )}
                    {msg.meta.degraded === "true" && (
                      <span className="flex items-center gap-2 text-harbor-coral">
                        <span className="led" style={{ background: "var(--harbor-coral)" }} />
                        DEGRADED
                      </span>
                    )}
                  </div>
                )}

                {msg.sources && msg.sources.length > 0 && (
                  <div className="flex flex-wrap gap-2 border-t border-harbor-line px-4 py-2.5 font-mono text-[11px] text-harbor-muted">
                    {msg.sources.map((s) => (
                      <span
                        key={s.rank}
                        title={`similarity ${s.score}`}
                        className="rounded-sm border border-harbor-line px-2 py-0.5"
                      >
                        <span className="text-harbor-beacon">[{s.rank}]</span> {s.title} · {s.score}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )
        )}
      </div>

      <div className="tick-rule" />
      <div className="px-4 py-4">
        <div className="mx-auto flex w-full max-w-3xl items-center gap-2 rounded-md border border-harbor-line bg-harbor-surface px-3 transition-colors focus-within:border-harbor-beacon">
          <span className="font-mono text-harbor-beacon">▸</span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            placeholder="ask about Pods, Deployments, Services…"
            disabled={busy}
            className="flex-1 bg-transparent py-3 font-sans text-harbor-fg outline-none placeholder:text-harbor-muted disabled:opacity-60"
          />
          <button
            onClick={() => send(input)}
            disabled={busy || !input.trim()}
            className="rounded-sm bg-harbor-beacon px-4 py-1.5 font-mono text-xs uppercase tracking-[0.14em] text-harbor-ink transition-opacity disabled:opacity-40"
          >
            {busy ? "···" : "send"}
          </button>
        </div>
      </div>
    </div>
  );
}
