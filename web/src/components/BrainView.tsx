"use client";

import { useEffect, useState } from "react";
import { fetchGraph, type GraphData } from "@/lib/api";
import { BrainGraph } from "./BrainGraph";

export function BrainView() {
  const [data, setData] = useState<GraphData | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchGraph(false)
      .then(async (g) => {
        if (cancelled) return;
        if (g.n_trades === 0) {
          const demo = await fetchGraph(true);
          if (cancelled) return;
          setData(demo);
          setIsDemo(true);
        } else {
          setData(g);
          setIsDemo(false);
        }
      })
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading)
    return (
      <div className="py-20 text-center text-[10px] mono text-[var(--muted)] animate-pulse">
        loading the bot brain…
      </div>
    );
  if (error) return <div className="text-sm text-[var(--danger-fg)]">brain unavailable · {error}</div>;
  if (!data) return null;

  const sigNodes = data.nodes.filter((n) => n.type === "signal");
  const vizNodes = showAll ? data.nodes : sigNodes;
  const vizIds = new Set(vizNodes.map((n) => n.id));
  const vizEdges = data.edges.filter((e) => vizIds.has(e.source) && vizIds.has(e.target));
  const minTrades = data.insights.summary.min_trades;
  const s = data.insights.summary;

  return (
    <div className="space-y-4">
      {isDemo && (
        <div className="rounded-md ring-border bg-[var(--surface-2)] px-4 py-2.5 text-xs text-[var(--muted)]">
          <span className="text-[var(--accent)]">preview · sample data</span> — no real trades logged yet.
          The brain fills in (and this banner disappears) as the paper bot opens and closes trades. Set up
          Alpaca, then run <span className="mono text-white">bot-run --execute</span> to start feeding it.
        </div>
      )}

      <div className="flex justify-end">
        <div className="flex gap-0.5 bg-[var(--surface-2)] rounded p-0.5 text-[10px] mono">
          {([["all", true], ["signals only", false]] as const).map(([label, val]) => (
            <button
              key={label}
              onClick={() => setShowAll(val)}
              className={
                "px-2 py-0.5 rounded transition-colors " +
                (showAll === val ? "bg-white/10 text-white" : "text-[var(--muted)] hover:text-white")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <BrainGraph nodes={vizNodes} edges={vizEdges} minTrades={minTrades} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Panel title="strongest signals">
          {data.insights.signals.best.length ? (
            data.insights.signals.best.slice(0, 6).map((r, i) => (
              <Row key={i} label={r.signal} n={r.n} wr={r.win_rate} r={r.avg_r} />
            ))
          ) : (
            <Empty min={minTrades} />
          )}
        </Panel>
        <Panel title="weakest signals">
          {data.insights.signals.worst.length ? (
            data.insights.signals.worst.slice(0, 6).map((r, i) => (
              <Row key={i} label={r.signal} n={r.n} wr={r.win_rate} r={r.avg_r} />
            ))
          ) : (
            <Empty min={minTrades} />
          )}
        </Panel>
        <Panel title="best combinations">
          {data.insights.combos.length ? (
            data.insights.combos.slice(0, 6).map((c, i) => (
              <Row key={i} label={c.combo.join(" + ")} n={c.n} wr={c.win_rate} r={c.avg_r} />
            ))
          ) : (
            <Empty min={minTrades} />
          )}
        </Panel>
      </div>

      <div className="text-[10px] mono text-[var(--muted)]">
        {s.n_trades} trades · {data.nodes.length} nodes · {data.edges.length} edges ·{" "}
        {s.signals_actionable} actionable signals (≥{minTrades} trades)
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md ring-border bg-[var(--surface)] p-4">
      <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)] mb-2">{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, n, wr, r }: { label: string; n: number; wr: number; r: number }) {
  return (
    <div className="flex items-center justify-between text-[11px] mono gap-2">
      <span className="truncate text-[var(--muted)]">{label}</span>
      <span className="flex items-center gap-2 shrink-0">
        <span className="text-[var(--muted)] opacity-60">{n}·{Math.round(wr * 100)}%</span>
        <span className="tabular-nums" style={{ color: r >= 0 ? "#6ee787" : "#f56e7d" }}>
          {r >= 0 ? "+" : ""}
          {r.toFixed(2)}R
        </span>
      </span>
    </div>
  );
}

function Empty({ min }: { min: number }) {
  return <div className="text-[10px] mono text-[var(--muted)] opacity-60">needs ≥{min} trades/signal</div>;
}
