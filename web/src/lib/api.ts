export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export type FactorScore = {
  score: number;
  signals: Record<string, unknown> & { flag?: string | null };
};

export type PressureScore = {
  score: number;
  components: { lending: number; gamma: number; social: number };
  raw: { L: number; G: number; S: number };
};

export type TickerResult = {
  ticker: string;
  name: string;
  price: number | null;
  market_cap: number | null;
  score: number;
  pressure_score?: PressureScore;
  factors: {
    sentiment: FactorScore;
    options: FactorScore;
    si: FactorScore;
    ta: FactorScore;
    catalyst: FactorScore;
  };
  flags: string[];
  excluded: boolean;
  exclude_reason: string | null;
  as_of: string;
  errors: Record<string, string>;
  weights?: { sentiment: number; options: number; si: number; ta: number; catalyst: number };
};

export type ScanResult = {
  as_of: string;
  universe_size: number;
  scored: number;
  returned: number;
  weights: Record<string, number>;
  min_score: number;
  results: TickerResult[];
  excluded: { ticker: string; reason: string }[];
  cached?: boolean;
  cache_age_seconds?: number;
  cache_stale?: boolean;
};

export type SwingResult = {
  ticker: string;
  name: string;
  price: number | null;
  market_cap: number | null;
  score: number;
  factors: {
    stage2: FactorScore;
    breakout: FactorScore;
    rs: FactorScore;
    catalyst: FactorScore;
    smart_money: FactorScore;
  };
  flags: string[];
  excluded: boolean;
  exclude_reason: string | null;
  as_of: string;
};

export type SwingScanResult = {
  as_of: string;
  universe_size: number;
  scored: number;
  returned: number;
  weights: Record<string, number>;
  min_score: number;
  regime: { regime: string; multiplier: number };
  results: SwingResult[];
  excluded: { ticker: string; reason: string }[];
  cached?: boolean;
  cache_age_seconds?: number;
  cache_stale?: boolean;
};

export function fetchSwingScan(params?: {
  limit?: number;
  min_score?: number;
}): Promise<SwingScanResult> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.min_score) qs.set("min_score", String(params.min_score));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return jsonFetch<SwingScanResult>(`/api/swing-scan${suffix}`);
}

export type Narrative = {
  ticker: string;
  score: number;
  narrative: {
    tldr: string;
    bull: string[];
    bear: string[];
    model_used: string;
  };
};

export type Idea = {
  idea_id: string;
  ticker: string;
  status: "open" | "closed" | "postmortemed";
  opened_at: string;
  score_at_entry: number;
  factors_at_entry: Record<string, number>;
  thesis: string;
  invalidation: string;
  time_stop: string | null;
  entry_ref_price: number | null;
  notes: string;
  updates: Record<string, unknown>[];
  closed: {
    ts: string;
    exit_ref_price: number | null;
    close_reason: string;
    days_held: number;
    peak_drawup_pct: number | null;
    peak_drawdown_pct: number | null;
  } | null;
  postmortem: {
    ts: string;
    outcome: "win" | "loss" | "flat";
    return_ref_pct: number | null;
    what_worked: string;
    what_missed: string;
    factor_calibration: Record<string, string>;
    lesson: string;
  } | null;
};

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export function fetchScan(params?: {
  limit?: number;
  min_score?: number;
  min_pressure?: number;
  sort_by?: "composite" | "pressure";
  tickers?: string;
}): Promise<ScanResult> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.min_score) qs.set("min_score", String(params.min_score));
  if (params?.min_pressure) qs.set("min_pressure", String(params.min_pressure));
  if (params?.sort_by) qs.set("sort_by", params.sort_by);
  if (params?.tickers) qs.set("tickers", params.tickers);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return jsonFetch<ScanResult>(`/api/scan${suffix}`);
}

export function fetchTicker(symbol: string): Promise<TickerResult> {
  return jsonFetch<TickerResult>(`/api/ticker/${symbol.toUpperCase()}`);
}

export function fetchNarrative(symbol: string): Promise<Narrative> {
  return jsonFetch<Narrative>(`/api/ticker/${symbol.toUpperCase()}/narrative`);
}

export type Bar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type ChartData = {
  ticker: string;
  period: string;
  as_of: string;
  bars: Bar[];
  levels: {
    entry: number;
    stop: number;
    tp: number;
    atr: number;
    risk_pct: number;
    rr: number;
    tp_pct: number;
    sl_basis: string;
    tp_basis: string;
    ladder: { r: number; price: number }[];
    poc: number | null;
    support: number | null;
    resistance: number | null;
  };
};

export function fetchChart(symbol: string, period: string = "3mo"): Promise<ChartData> {
  return jsonFetch<ChartData>(`/api/ticker/${symbol.toUpperCase()}/chart?period=${period}`);
}

export type GraphNode = {
  id: string;
  type: string;
  label: string;
  n: number;
  wins: number;
  win_rate: number;
  avg_r: number;
  avg_plpc: number;
};
export type GraphEdge = {
  source: string;
  target: string;
  type: string;
  n: number;
  wins: number;
  avg_r: number;
  win_rate: number;
};
export type SignalRow = { signal: string; n: number; win_rate: number; avg_r: number };
export type GraphData = {
  n_trades: number;
  demo: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  insights: {
    summary: {
      n_trades: number;
      n_nodes: number;
      n_edges: number;
      signals_actionable: number;
      min_trades: number;
      underpowered: boolean;
    };
    signals: { best: SignalRow[]; worst: SignalRow[] };
    combos: { combo: string[]; n: number; win_rate: number; avg_r: number }[];
  };
};

export function fetchGraph(demo = false): Promise<GraphData> {
  return jsonFetch<GraphData>(`/api/graph${demo ? "?demo=true" : ""}`);
}

export type OptionContract = {
  ticker: string;
  expiry: string;
  dte: number;
  strike: number;
  bid: number;
  ask: number;
  last: number;
  mid: number;
  spread_pct: number | null;
  volume: number;
  open_interest: number;
  iv: number;
  iv_stale?: boolean;
  delta: number;
  gamma: number | null;
  theta: number | null;
  breakeven: number;
  breakeven_pct_from_spot: number;
  cost_per_contract: number;
  pct_otm: number;
  near_max_gamma: boolean;
  chain_stale?: boolean;
  score: number;
  rationale: string;
};

export type OptionsRec = {
  ticker: string;
  spot: number;
  as_of: string;
  risk_free_rate: number;
  max_gamma_strike: number | null;
  expiries_scanned: string[];
  candidates_total: number;
  recommendations: OptionContract[];
  stale_quotes?: boolean;
  filters: Record<string, number>;
};

export function fetchOptions(symbol: string, top: number = 8): Promise<OptionsRec> {
  return jsonFetch<OptionsRec>(`/api/ticker/${symbol.toUpperCase()}/options?top=${top}`);
}

export type Quicktake = {
  ticker: string;
  score: number;
  take: string;
  model_used: string;
  cached?: boolean;
};

export function fetchQuicktake(symbol: string): Promise<Quicktake> {
  return jsonFetch<Quicktake>(`/api/ticker/${symbol.toUpperCase()}/quicktake`);
}

export type ZeroDteContract = {
  ticker: string;
  side: "call" | "put";
  strike: number;
  expiry: string;
  bid: number;
  ask: number;
  mid: number;
  spread_pct: number | null;
  volume: number;
  open_interest: number;
  iv: number;
  delta: number;
  cost_per_contract: number;
  breakeven: number;
  pct_otm: number;
  expected_move_dollars: number;
  expected_move_pct: number | null;
  p_2x: number;
  p_5x: number;
  p_10x: number;
  tp1_price: number;
  tp2_price: number;
  tp3_price: number;
  sl_price: number;
  tp1_spot: number | null;
  tp2_spot: number | null;
  tp3_spot: number | null;
  sl_spot: number | null;
  score: number;
};

export type ZeroDteNarrative = {
  ticker: string;
  as_of: string;
  spot: number;
  expiry: string;
  narrative: {
    tldr: string;
    calls: string[];
    puts: string[];
    risk: string[];
    model_used: string;
  };
  cached?: boolean;
};

export function fetchZeroDteNarrative(ticker: string): Promise<ZeroDteNarrative> {
  return jsonFetch<ZeroDteNarrative>(`/api/zero-dte/${ticker.toUpperCase()}/narrative`);
}

export type ZeroDteTickerResult = {
  ticker: string;
  spot: number;
  expiry: string;
  as_of: string;
  chain_stale: boolean;
  hours_until_close: number;
  calls: ZeroDteContract[];
  puts: ZeroDteContract[];
  candidates_scored: number;
};

export type ZeroDteScreen = {
  as_of: string;
  ok: boolean;
  blocked_reason: "closed" | "pre_open" | "auction_noise" | "theta_cliff" | null;
  expiry?: string;
  universe: string[];
  errors?: Record<string, string>;
  filters?: Record<string, number | number[]>;
  results: ZeroDteTickerResult[];
};

export function fetchZeroDte(top_per_side: number = 3): Promise<ZeroDteScreen> {
  return jsonFetch<ZeroDteScreen>(`/api/zero-dte?top_per_side=${top_per_side}`);
}

export function fetchIdeas(status?: Idea["status"]): Promise<{ count: number; ideas: Idea[] }> {
  const qs = status ? `?status=${status}` : "";
  return jsonFetch(`/api/ideas${qs}`);
}

export function fetchIdea(id: string): Promise<Idea> {
  return jsonFetch<Idea>(`/api/ideas/${id}`);
}

export function openIdea(body: {
  ticker: string;
  thesis: string;
  invalidation: string;
  time_stop?: string;
  force?: boolean;
  notes?: string;
}): Promise<Record<string, unknown>> {
  return jsonFetch(`/api/ideas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function closeIdea(
  id: string,
  body: {
    close_reason: string;
    exit_ref_price?: number;
    peak_drawup_pct?: number;
    peak_drawdown_pct?: number;
  },
): Promise<Record<string, unknown>> {
  return jsonFetch(`/api/ideas/${id}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function submitPostmortem(
  id: string,
  body: {
    outcome: "win" | "loss" | "flat";
    return_ref_pct?: number;
    what_worked: string;
    what_missed: string;
    factor_calibration: Record<string, string>;
    lesson: string;
  },
): Promise<Record<string, unknown>> {
  return jsonFetch(`/api/ideas/${id}/postmortem`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function formatMarketCap(mcap: number | null): string {
  if (!mcap) return "–";
  if (mcap >= 1e12) return `$${(mcap / 1e12).toFixed(2)}T`;
  if (mcap >= 1e9) return `$${(mcap / 1e9).toFixed(2)}B`;
  if (mcap >= 1e6) return `$${(mcap / 1e6).toFixed(1)}M`;
  return `$${mcap.toLocaleString()}`;
}

export function formatPrice(p: number | null): string {
  if (p == null) return "–";
  return `$${p.toFixed(2)}`;
}

export function scoreColor(score: number): string {
  if (score >= 75) return "text-[var(--success-fg)] bg-[var(--success)]/15 border-[var(--success)]/40";
  if (score >= 60) return "text-[var(--warning-fg)] bg-[var(--warning)]/15 border-[var(--warning)]/40";
  if (score >= 40) return "text-[var(--foreground)] bg-white/5 border-[var(--border-strong)]";
  return "text-[var(--muted)] bg-transparent border-[var(--border)]";
}
