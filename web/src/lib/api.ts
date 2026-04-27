export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export type FactorScore = {
  score: number;
  signals: Record<string, unknown> & { flag?: string | null };
};

export type TickerResult = {
  ticker: string;
  name: string;
  price: number | null;
  market_cap: number | null;
  score: number;
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
};

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
  tickers?: string;
}): Promise<ScanResult> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.min_score) qs.set("min_score", String(params.min_score));
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
    breakout_60d: number;
    target_2x: number;
    target_5x: number;
    target_10x: number;
  };
};

export function fetchChart(symbol: string, period: string = "3mo"): Promise<ChartData> {
  return jsonFetch<ChartData>(`/api/ticker/${symbol.toUpperCase()}/chart?period=${period}`);
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
