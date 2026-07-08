import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import ChatView from "./ChatView";
import Dashboard from "./Dashboard";

type View = "chat" | "dashboard";
type Theme = "dark" | "light";

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "dark"
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("harbor-theme", theme);
    } catch {
      /* storage unavailable — theme still applies for this session */
    }
  }, [theme]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-end justify-between px-6 pb-3 pt-5">
        <div className="flex items-baseline gap-3">
          <span className="led led-live mb-[3px] self-center" aria-hidden />
          <span className="font-display text-lg font-bold tracking-[0.24em] text-harbor-fg">
            HARBOR
          </span>
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-harbor-muted">
            llm reliability control
          </span>
        </div>

        <div className="flex items-center gap-5">
          <button
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title="Toggle theme"
            className="flex items-center gap-1.5 rounded-sm border border-harbor-line px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] text-harbor-muted transition-colors hover:border-harbor-beacon hover:text-harbor-fg"
          >
            <span aria-hidden>{theme === "dark" ? "☀" : "☾"}</span>
            <span>{theme === "dark" ? "light" : "dark"}</span>
          </button>

          <nav className="flex gap-6 font-mono text-xs uppercase tracking-[0.16em]">
            <Tab active={view === "chat"} onClick={() => setView("chat")}>
              chat
            </Tab>
            <Tab active={view === "dashboard"} onClick={() => setView("dashboard")}>
              quality
            </Tab>
          </nav>
        </div>
      </header>
      <div className="tick-rule" />

      <main className="min-h-0 flex-1">
        {view === "chat" ? <ChatView /> : <Dashboard />}
      </main>
    </div>
  );
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button onClick={onClick} className="group pb-1">
      <span className={active ? "text-harbor-beacon" : "text-harbor-muted group-hover:text-harbor-fg"}>
        {children}
      </span>
      <span
        className={
          "mt-1 block h-px transition-colors " +
          (active ? "bg-harbor-beacon" : "bg-transparent group-hover:bg-harbor-line")
        }
      />
    </button>
  );
}
