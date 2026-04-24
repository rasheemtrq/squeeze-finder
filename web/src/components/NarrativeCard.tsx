"use client";

import { useEffect, useState } from "react";
import { Sparkles, TrendingUp, TrendingDown } from "lucide-react";
import { fetchNarrative, type Narrative } from "@/lib/api";

export function NarrativeCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Narrative | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchNarrative(symbol)
      .then((n) => {
        if (!cancelled) setData(n);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return (
    <div className="rounded-md ring-border bg-[var(--surface)] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[var(--accent)]" />
          <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
            ai analyst · free model
          </div>
        </div>
        {data && (
          <div className="text-[10px] mono text-[var(--muted)]">
            {data.narrative.model_used}
          </div>
        )}
      </div>

      {loading && <NarrativeSkeleton />}

      {error && (
        <div className="text-sm space-y-1">
          <div className="text-[var(--danger-fg)]">narrative unavailable</div>
          <div className="text-[var(--muted)] mono text-xs">{error}</div>
          <div className="text-[var(--muted)] text-xs">
            check OPENROUTER_API_KEY or free-tier saturation
          </div>
        </div>
      )}

      {data && !loading && !error && (
        <>
          <div className="text-sm leading-relaxed">{data.narrative.tldr}</div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <TrendingUp className="w-3.5 h-3.5 text-[var(--success-fg)]" />
                <span className="text-[10px] mono uppercase tracking-wider text-[var(--success-fg)]">
                  bull
                </span>
              </div>
              <ul className="space-y-2 text-xs leading-relaxed">
                {data.narrative.bull.map((b, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-[var(--success-fg)] mono">›</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <TrendingDown className="w-3.5 h-3.5 text-[var(--danger-fg)]" />
                <span className="text-[10px] mono uppercase tracking-wider text-[var(--danger-fg)]">
                  bear / invalidation
                </span>
              </div>
              <ul className="space-y-2 text-xs leading-relaxed">
                {data.narrative.bear.map((b, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-[var(--danger-fg)] mono">›</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function NarrativeSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-3 w-full bg-white/5 rounded" />
      <div className="h-3 w-[90%] bg-white/5 rounded" />
      <div className="h-3 w-3/4 bg-white/5 rounded" />
      <div className="grid grid-cols-2 gap-4 pt-3">
        <div className="space-y-2">
          <div className="h-2 w-10 bg-white/5 rounded" />
          <div className="h-2 w-full bg-white/5 rounded" />
          <div className="h-2 w-[90%] bg-white/5 rounded" />
          <div className="h-2 w-[85%] bg-white/5 rounded" />
        </div>
        <div className="space-y-2">
          <div className="h-2 w-14 bg-white/5 rounded" />
          <div className="h-2 w-full bg-white/5 rounded" />
          <div className="h-2 w-[92%] bg-white/5 rounded" />
          <div className="h-2 w-[80%] bg-white/5 rounded" />
        </div>
      </div>
    </div>
  );
}
