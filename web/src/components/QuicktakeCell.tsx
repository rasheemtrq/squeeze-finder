"use client";

import { useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { fetchQuicktake, type Quicktake } from "@/lib/api";

export function QuicktakeCell({ ticker }: { ticker: string }) {
  const [data, setData] = useState<Quicktake | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (data || loading) return;
    setLoading(true);
    setError(null);
    try {
      const t = await fetchQuicktake(ticker);
      setData(t);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  if (data) {
    return (
      <div className="flex items-start gap-1.5 max-w-[300px] text-[11px] leading-snug">
        <Sparkles className="w-3 h-3 text-[var(--accent)] shrink-0 mt-0.5" />
        <span className="text-[var(--foreground)]">{data.take}</span>
      </div>
    );
  }

  if (error) {
    return (
      <span className="text-[10px] mono text-[var(--danger-fg)]" title={error}>
        ✗ take failed
      </span>
    );
  }

  if (loading) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] mono text-[var(--muted)]">
        <Loader2 className="w-3 h-3 animate-spin" /> …
      </span>
    );
  }

  return (
    <button
      onClick={load}
      className="inline-flex items-center gap-1 text-[10px] mono uppercase tracking-wider text-[var(--accent)] hover:text-white transition-colors px-1.5 py-0.5 rounded border border-[var(--accent)]/30 hover:bg-[var(--accent)]/10"
      title="Generate Haiku take (~2s, $0.001)"
    >
      <Sparkles className="w-2.5 h-2.5" />
      take
    </button>
  );
}
