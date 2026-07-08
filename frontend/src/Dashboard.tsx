import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { API_BASE } from "./api";

type Run = {
  id: number;
  prompt_version: string;
  model: string;
  status: string;
  num_cases: number;
  mean_score: number | null;
  pass_rate: number | null;
  per_evaluator: Record<string, number>;
  finished_at: string | null;
};

const AXIS = "#7f9c99";
const GRID = "#1d3a3f";
const BEACON = "#f0a94a";
const PATINA = "#54c8ad";
const TOOLTIP = { background: "#0f1e21", border: "1px solid #1d3a3f", fontFamily: "IBM Plex Mono, monospace", fontSize: 12 };

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [cache, setCache] = useState<{ entries: number | null; total_hits: number | null }>({
    entries: null,
    total_hits: null,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [r, c] = await Promise.all([
          fetch(`${API_BASE}/api/eval/runs`).then((x) => x.json()),
          fetch(`${API_BASE}/api/cache/summary`).then((x) => x.json()),
        ]);
        setRuns(r);
        setCache(c);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

  if (error)
    return (
      <div className="p-8 font-mono text-sm text-harbor-coral">
        signal lost — {error}
      </div>
    );
  if (runs.length === 0)
    return (
      <div className="p-8 font-mono text-sm text-harbor-muted">
        no eval runs logged. run <span className="text-harbor-beacon">make eval-run</span> and refresh.
      </div>
    );

  // API returns newest-first; chronological for the trend charts.
  const chrono = [...runs].reverse();
  const trend = chrono.map((r) => ({
    run: `#${r.id}`,
    mean: r.mean_score ?? 0,
    pass: r.pass_rate ?? 0,
  }));
  const latest = runs[0];
  const evalBars = Object.entries(latest.per_evaluator || {}).map(([evaluator, mean]) => ({
    evaluator: evaluator.replace(/_/g, " "),
    mean,
  }));

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 overflow-y-auto p-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Readout label="latest mean score" value={fmt(latest.mean_score)} />
        <Readout label="latest pass rate" value={pct(latest.pass_rate)} />
        <Readout label="eval runs logged" value={String(runs.length)} />
        <Readout label="cache entries" value={cache.entries == null ? "—" : String(cache.entries)} />
      </div>

      <Panel title="quality over runs · mean score & pass rate">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={trend} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 5" />
            <XAxis dataKey="run" stroke={AXIS} fontSize={11} fontFamily="IBM Plex Mono, monospace" />
            <YAxis domain={[0, 1]} stroke={AXIS} fontSize={11} fontFamily="IBM Plex Mono, monospace" />
            <Tooltip contentStyle={TOOLTIP} cursor={{ stroke: GRID }} />
            <Line type="monotone" dataKey="mean" stroke={BEACON} strokeWidth={2} dot={{ r: 2, fill: BEACON }} name="mean score" />
            <Line type="monotone" dataKey="pass" stroke={PATINA} strokeWidth={2} dot={{ r: 2, fill: PATINA }} name="pass rate" />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title={`per-evaluator mean · latest run #${latest.id} (${latest.prompt_version})`}>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={evalBars} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 5" vertical={false} />
            <XAxis dataKey="evaluator" stroke={AXIS} fontSize={10} fontFamily="IBM Plex Mono, monospace" />
            <YAxis domain={[0, 1]} stroke={AXIS} fontSize={11} fontFamily="IBM Plex Mono, monospace" />
            <Tooltip contentStyle={TOOLTIP} cursor={{ fill: "rgba(240,169,74,0.06)" }} />
            <Bar dataKey="mean" fill={BEACON} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="run log">
        <table className="w-full text-left font-mono text-[13px]">
          <thead className="font-mono text-[10px] uppercase tracking-[0.14em] text-harbor-muted">
            <tr>
              <th className="py-2 font-normal">run</th>
              <th className="font-normal">prompt</th>
              <th className="font-normal">mean</th>
              <th className="font-normal">pass</th>
              <th className="font-normal">cases</th>
              <th className="font-normal">status</th>
              <th className="font-normal">finished</th>
            </tr>
          </thead>
          <tbody className="text-harbor-fg">
            {runs.map((r) => (
              <tr key={r.id} className="border-t border-harbor-line">
                <td className="py-2 text-harbor-beacon">#{r.id}</td>
                <td className="text-harbor-muted">{r.prompt_version}</td>
                <td>{fmt(r.mean_score)}</td>
                <td>{pct(r.pass_rate)}</td>
                <td>{r.num_cases}</td>
                <td className="text-harbor-muted">{r.status}</td>
                <td className="text-harbor-muted">
                  {r.finished_at ? r.finished_at.slice(0, 19).replace("T", " ") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-harbor-line bg-harbor-surface p-4">
      <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-harbor-muted">{label}</div>
      <div className="mt-2 font-display text-3xl font-semibold text-harbor-fg">{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-harbor-line bg-harbor-surface p-4">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-harbor-muted">{title}</div>
      <div className="tick-rule mb-3" />
      {children}
    </div>
  );
}

const fmt = (n: number | null) => (n == null ? "—" : n.toFixed(3));
const pct = (n: number | null) => (n == null ? "—" : `${(n * 100).toFixed(0)}%`);
