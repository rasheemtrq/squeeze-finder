"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/lib/api";

type P = { x: number; y: number; vx: number; vy: number };
type View = { x: number; y: number; k: number };

const W = 860;
const H = 520;

const TYPE_COLOR: Record<string, string> = {
  ticker: "#3b9eff",
  strategy: "#a371f7",
  dte_bucket: "#f5d16e",
  delta_bucket: "#e8a13a",
};

function nodeColor(nd: GraphNode, minTrades: number): string {
  if (nd.type !== "signal") return TYPE_COLOR[nd.type] || "#8f8f8f";
  if (nd.n < minTrades) return "#6b7280"; // thin — not actionable
  if (nd.avg_r > 0.2) return "#6ee787";
  if (nd.avg_r < -0.2) return "#f56e7d";
  return "#8f8f8f";
}

function forceStep(pos: Record<string, P>, nodes: GraphNode[], edges: GraphEdge[], pinned: string | null) {
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = pos[nodes[i].id];
      const b = pos[nodes[j].id];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const d2 = dx * dx + dy * dy + 0.01;
      const d = Math.sqrt(d2);
      const rep = 5200 / d2;
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
    const att = (d - 95) * 0.01 * (1 + Math.min(e.n, 20) * 0.025);
    a.vx += (dx / d) * att;
    a.vy += (dy / d) * att;
    b.vx -= (dx / d) * att;
    b.vy -= (dy / d) * att;
  }
  for (const nd of nodes) {
    const p = pos[nd.id];
    if (nd.id === pinned) {
      p.vx = 0;
      p.vy = 0;
      continue;
    }
    p.vx += (W / 2 - p.x) * 0.004;
    p.vy += (H / 2 - p.y) * 0.004;
    p.x += p.vx * 0.82;
    p.y += p.vy * 0.82;
    p.vx *= 0.82;
    p.vy *= 0.82;
  }
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
  const svgRef = useRef<SVGSVGElement>(null);
  const posRef = useRef<Record<string, P>>({});
  const alphaRef = useRef(1);
  const runningRef = useRef(false);
  const dragRef = useRef<string | null>(null);
  const panRef = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const [, setTick] = useState(0);
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 });
  const [focus, setFocus] = useState<string | null>(null);
  const [hover, setHover] = useState<{ nd: GraphNode; sx: number; sy: number } | null>(null);

  // (Re)seed positions when the graph changes.
  useEffect(() => {
    const pos: Record<string, P> = {};
    nodes.forEach((nd, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, nodes.length);
      pos[nd.id] = { x: W / 2 + Math.cos(a) * W * 0.3, y: H / 2 + Math.sin(a) * H * 0.3, vx: 0, vy: 0 };
    });
    posRef.current = pos;
    alphaRef.current = 1;
    startSim();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  function startSim() {
    if (runningRef.current) return;
    runningRef.current = true;
    const loop = () => {
      if (alphaRef.current > 0.02) {
        forceStep(posRef.current, nodes, edges, dragRef.current);
        alphaRef.current *= 0.99;
        setTick((t) => t + 1);
        requestAnimationFrame(loop);
      } else {
        runningRef.current = false;
      }
    };
    requestAnimationFrame(loop);
  }
  function reheat(a = 0.5) {
    alphaRef.current = Math.max(alphaRef.current, a);
    startSim();
  }

  const neighbors = useMemo(() => {
    if (!focus) return null;
    const s = new Set<string>([focus]);
    for (const e of edges) {
      if (e.source === focus) s.add(e.target);
      if (e.target === focus) s.add(e.source);
    }
    return s;
  }, [focus, edges]);

  const maxN = Math.max(...nodes.map((n) => n.n), 1);
  const radius = (n: number) => 6 + Math.sqrt(n / maxN) * 20;

  function toGraph(clientX: number, clientY: number) {
    const r = svgRef.current?.getBoundingClientRect();
    const sx = clientX - (r?.left ?? 0);
    const sy = clientY - (r?.top ?? 0);
    return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k };
  }

  // pointer drag (node) / pan (background)
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (dragRef.current) {
        const g = toGraph(e.clientX, e.clientY);
        const p = posRef.current[dragRef.current];
        if (p) {
          p.x = g.x;
          p.y = g.y;
          p.vx = 0;
          p.vy = 0;
        }
        reheat(0.3);
        setTick((t) => t + 1);
      } else if (panRef.current) {
        setView((v) => ({ ...v, x: panRef.current!.vx + (e.clientX - panRef.current!.x), y: panRef.current!.vy + (e.clientY - panRef.current!.y) }));
      }
    };
    const up = () => {
      dragRef.current = null;
      panRef.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  if (!nodes.length) {
    return (
      <div className="h-[300px] flex items-center justify-center rounded-md ring-border bg-[var(--surface)] text-[10px] mono text-[var(--muted)]">
        no nodes yet — the brain is empty
      </div>
    );
  }

  const pos = posRef.current;
  const active = (id: string) => !neighbors || neighbors.has(id);

  return (
    <div className="relative w-full overflow-hidden rounded-md ring-border bg-[var(--surface)]">
      <svg
        ref={svgRef}
        width="100%"
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        style={{ touchAction: "none", cursor: panRef.current ? "grabbing" : "grab" }}
        onPointerDown={(e) => {
          panRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
          setFocus(null);
        }}
        onWheel={(e) => {
          const r = svgRef.current!.getBoundingClientRect();
          const sx = e.clientX - r.left;
          const sy = e.clientY - r.top;
          const dk = e.deltaY < 0 ? 1.12 : 1 / 1.12;
          setView((v) => {
            const k = Math.max(0.3, Math.min(4, v.k * dk));
            return { k, x: sx - ((sx - v.x) / v.k) * k, y: sy - ((sy - v.y) / v.k) * k };
          });
        }}
      >
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {edges.map((e, i) => {
            const a = pos[e.source];
            const b = pos[e.target];
            if (!a || !b) return null;
            const on = !neighbors || (neighbors.has(e.source) && neighbors.has(e.target) && (e.source === focus || e.target === focus));
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={on && focus ? "#3b9eff" : "#ffffff"}
                strokeOpacity={focus ? (on ? 0.5 : 0.03) : Math.min(0.22, 0.03 + e.n * 0.012)}
                strokeWidth={on && focus ? 1.5 : 1}
              />
            );
          })}
          {nodes.map((nd) => {
            const p = pos[nd.id];
            if (!p) return null;
            const rad = radius(nd.n);
            const act = active(nd.id);
            return (
              <g
                key={nd.id}
                opacity={act ? 1 : 0.12}
                style={{ cursor: "pointer" }}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  dragRef.current = nd.id;
                  reheat(0.3);
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  setFocus((f) => (f === nd.id ? null : nd.id));
                }}
                onPointerEnter={(e) => setHover({ nd, sx: e.clientX, sy: e.clientY })}
                onPointerLeave={() => setHover(null)}
              >
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={rad}
                  fill={nodeColor(nd, minTrades)}
                  fillOpacity={0.88}
                  stroke={focus === nd.id ? "#ffffff" : "#0a0a0a"}
                  strokeWidth={focus === nd.id ? 2.5 : 1.5}
                />
                {(rad >= 13 || focus === nd.id) && (
                  <text x={p.x} y={p.y + rad + 9} textAnchor="middle" fontSize={9} fill="#8f8f8f" className="mono">
                    {nd.label.length > 18 ? nd.label.slice(0, 17) + "…" : nd.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded bg-black/85 px-3 py-2 text-[10px] mono ring-border"
          style={{
            left: Math.min((svgRef.current?.getBoundingClientRect().width ?? W) - 200, hover.sx - (svgRef.current?.getBoundingClientRect().left ?? 0) + 12),
            top: hover.sy - (svgRef.current?.getBoundingClientRect().top ?? 0) + 12,
          }}
        >
          <div className="text-white">{hover.nd.label}</div>
          <div className="text-[var(--muted)]">
            {hover.nd.type} · {hover.nd.n} trades · {Math.round(hover.nd.win_rate * 100)}% win · avg{" "}
            {hover.nd.avg_r >= 0 ? "+" : ""}
            {hover.nd.avg_r.toFixed(2)}R
          </div>
        </div>
      )}

      <div className="absolute top-2 left-3 text-[9px] mono text-[var(--muted)]">
        drag node · scroll to zoom · drag bg to pan · <span className="text-white">click a node to spotlight its connections</span>
        {focus && <span className="text-[var(--accent)]"> · focused: {nodes.find((n) => n.id === focus)?.label}</span>}
      </div>
      <div className="absolute bottom-2 right-3 flex gap-3 text-[9px] mono text-[var(--muted)]">
        <span><span style={{ color: "#6ee787" }}>●</span> +signal</span>
        <span><span style={{ color: "#f56e7d" }}>●</span> −signal</span>
        <span><span style={{ color: "#3b9eff" }}>●</span> ticker</span>
        <span><span style={{ color: "#a371f7" }}>●</span> strategy</span>
      </div>
    </div>
  );
}
