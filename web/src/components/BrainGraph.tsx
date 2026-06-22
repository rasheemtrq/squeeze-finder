"use client";

import { useMemo, useState } from "react";
import type { GraphEdge, GraphNode } from "@/lib/api";

type P = { x: number; y: number; vx: number; vy: number };

function colorFor(avgR: number, n: number, minTrades: number): string {
  if (n < minTrades) return "#6b7280"; // gray — not yet actionable
  if (avgR > 0.2) return "#6ee787"; // green — positive edge
  if (avgR < -0.2) return "#f56e7d"; // red — negative edge
  return "#8f8f8f"; // neutral
}

// Tiny deterministic force layout (repulsion + edge springs + centering). No deps.
function layout(nodes: GraphNode[], edges: GraphEdge[], W: number, H: number, iters = 400): Record<string, P> {
  const pos: Record<string, P> = {};
  nodes.forEach((nd, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, nodes.length);
    pos[nd.id] = { x: W / 2 + Math.cos(a) * W * 0.28, y: H / 2 + Math.sin(a) * H * 0.28, vx: 0, vy: 0 };
  });
  for (let it = 0; it < iters; it++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos[nodes[i].id];
        const b = pos[nodes[j].id];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 0.01;
        const d = Math.sqrt(d2);
        const rep = 4500 / d2;
        a.vx += (dx / d) * rep;
        a.vy += (dy / d) * rep;
        b.vx -= (dx / d) * rep;
        b.vy -= (dy / d) * rep;
      }
    }
    for (const e of edges) {
      const a = pos[e.source];
      const b = pos[e.target];
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const att = (d - 90) * 0.012 * (1 + Math.min(e.n, 20) * 0.03);
      a.vx += (dx / d) * att;
      a.vy += (dy / d) * att;
      b.vx -= (dx / d) * att;
      b.vy -= (dy / d) * att;
    }
    for (const nd of nodes) {
      const p = pos[nd.id];
      p.vx += (W / 2 - p.x) * 0.003;
      p.vy += (H / 2 - p.y) * 0.003;
      p.x += p.vx * 0.8;
      p.y += p.vy * 0.8;
      p.vx *= 0.8;
      p.vy *= 0.8;
      p.x = Math.max(30, Math.min(W - 30, p.x));
      p.y = Math.max(24, Math.min(H - 24, p.y));
    }
  }
  return pos;
}

export function BrainGraph({
  nodes,
  edges,
  minTrades,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  minTrades: number;
}) {
  const W = 820;
  const H = 460;
  const [hover, setHover] = useState<GraphNode | null>(null);
  const pos = useMemo(() => layout(nodes, edges, W, H), [nodes, edges]);

  if (!nodes.length) {
    return (
      <div className="h-[300px] flex items-center justify-center rounded-md ring-border bg-[var(--surface)] text-[10px] mono text-[var(--muted)]">
        no signal nodes yet — the brain is empty
      </div>
    );
  }

  const maxN = Math.max(...nodes.map((n) => n.n), 1);
  const radius = (n: number) => 7 + Math.sqrt(n / maxN) * 22;

  return (
    <div className="relative w-full overflow-hidden rounded-md ring-border bg-[var(--surface)]">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        {edges.map((e, i) => {
          const a = pos[e.source];
          const b = pos[e.target];
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#ffffff"
              strokeOpacity={Math.min(0.25, 0.04 + e.n * 0.015)}
              strokeWidth={1}
            />
          );
        })}
        {nodes.map((nd) => {
          const p = pos[nd.id];
          if (!p) return null;
          const rad = radius(nd.n);
          return (
            <g
              key={nd.id}
              onMouseEnter={() => setHover(nd)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "pointer" }}
            >
              <circle
                cx={p.x}
                cy={p.y}
                r={rad}
                fill={colorFor(nd.avg_r, nd.n, minTrades)}
                fillOpacity={0.85}
                stroke="#0a0a0a"
                strokeWidth={1.5}
              />
              {rad >= 14 && (
                <text x={p.x} y={p.y + rad + 10} textAnchor="middle" fontSize={9} fill="#8f8f8f" className="mono">
                  {nd.label.length > 16 ? nd.label.slice(0, 15) + "…" : nd.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="absolute top-2 left-2 rounded bg-black/80 px-3 py-2 text-[10px] mono ring-border">
          <div className="text-white">{hover.label}</div>
          <div className="text-[var(--muted)]">
            {hover.n} trades · {Math.round(hover.win_rate * 100)}% win · avg {hover.avg_r >= 0 ? "+" : ""}
            {hover.avg_r.toFixed(2)}R
          </div>
        </div>
      )}
      <div className="absolute bottom-2 right-3 flex gap-3 text-[9px] mono text-[var(--muted)]">
        <span><span style={{ color: "#6ee787" }}>●</span> +edge</span>
        <span><span style={{ color: "#f56e7d" }}>●</span> −edge</span>
        <span><span style={{ color: "#6b7280" }}>●</span> thin (&lt;{minTrades})</span>
      </div>
    </div>
  );
}
