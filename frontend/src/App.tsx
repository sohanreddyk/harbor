import { useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

type Source = { rank: number; source: string; title: string; score: number };
type Message = { role: "user" | "assistant"; content: string; sources?: Source[] };

const SUGGESTIONS = [
  "What is a Pod in Kubernetes?",
  "How do rolling updates work in a Deployment?",
  "What are the different Service types?",
];

export default function App() {
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

      // Parse the SSE stream: events are separated by a blank line.
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const raw = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          handleEvent(raw);
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
    else if (event === "error") appendToAssistant(`\n\n[error: ${payload.message}]`);
    scrollToBottom();
  }

  // Pure updaters: create a new last-message object rather than mutating it,
  // so React 18 StrictMode's double-invoked updaters don't duplicate tokens.
  const appendToAssistant = (text: string) =>
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last?.role !== "assistant") return m;
      const updated = { ...last, content: last.content + text };
      return [...m.slice(0, -1), updated];
    });

  const setAssistantSources = (sources: Source[]) =>
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last?.role !== "assistant") return m;
      return [...m.slice(0, -1), { ...last, sources }];
    });

  return (
    <div className="flex h-full flex-col text-slate-100">
      <header className="border-b border-white/10 px-6 py-4">
        <h1 className="text-lg font-semibold">
          <span className="text-harbor-accent">Harbor</span>{" "}
          <span className="text-slate-400 font-normal">· documentation assistant</span>
        </h1>
      </header>

      <div ref={scrollRef} className="mx-auto w-full max-w-3xl flex-1 space-y-4 overflow-y-auto px-4 py-6">
        {messages.length === 0 && (
          <div className="space-y-3 pt-10 text-center text-slate-400">
            <p>Ask a question about the ingested Kubernetes corpus.</p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-white/10 bg-harbor-panel px-3 py-1.5 text-sm hover:border-harbor-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={msg.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                "max-w-[85%] rounded-2xl px-4 py-3 " +
                (msg.role === "user" ? "bg-harbor-accent text-slate-900" : "bg-harbor-panel")
              }
            >
              <p className="whitespace-pre-wrap leading-relaxed">
                {msg.content || (busy && msg.role === "assistant" ? "…" : "")}
              </p>
              {msg.sources && msg.sources.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-white/10 pt-2">
                  {msg.sources.map((s) => (
                    <span
                      key={s.rank}
                      title={`similarity ${s.score}`}
                      className="rounded bg-black/30 px-2 py-0.5 text-xs text-slate-300"
                    >
                      [{s.rank}] {s.title} · {s.score}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-white/10 px-4 py-4">
        <div className="mx-auto flex w-full max-w-3xl gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            placeholder="Ask about Pods, Deployments, Services…"
            disabled={busy}
            className="flex-1 rounded-xl border border-white/10 bg-harbor-panel px-4 py-3 outline-none focus:border-harbor-accent disabled:opacity-60"
          />
          <button
            onClick={() => send(input)}
            disabled={busy || !input.trim()}
            className="rounded-xl bg-harbor-accent px-5 py-3 font-medium text-slate-900 disabled:opacity-40"
          >
            {busy ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
