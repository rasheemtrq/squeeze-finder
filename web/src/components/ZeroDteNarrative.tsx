"use client";

import { useState } from "react";
import { Sparkles, TrendingUp, TrendingDown, ShieldAlert, Loader2 } from "lucide-react";
import { fetchZeroDteNarrative, type ZeroDteNarrative } from "@/lib/api";

export function ZeroDteNarrativeCard({ ticker }: { ticker: string }) {
  const [data, setData] = useState<ZeroDteNarrative | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const n = await fetchZeroDteNarrative(ticker);
      setData(n);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  if (!data && !loading && !error) {
    return (
      <button
        onClick={load}
        className="inline-flex items-center gap-1.5 text-[11px] mono uppercase tracking-wider text-[var(--accent)] hover:text-white transition-colors px-2 py-1 rounded border border-[var(--accent)]/40 hover:bg-[var(--accent)]/10"
      >
        <Sparkles className="w-3 h-3" />
        haiku analysis
      </button>
    );
  }

  return (
    <div className="border-t border-[var(--border)] bg-black/40 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5 text-[var(--accent)]" />
        <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
          tactical 0dte read
        </div>
        {data?.cached && (
          <span className="text-[10px] mono text-[var(--muted)]">cached</span>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> generating…
        </div>
      )}

      {error && (
        <div className="text-xs">
          <div className="text-[var(--danger-fg)]">narrative unavailable</div>
          <div className="text-[var(--muted)] mono">{error}</div>
        </div>
      )}

      {data && (
        <>
          <div className="text-sm leading-relaxed">{data.narrative.tldr}</div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
            {data.narrative.calls.length > 0 && (
              <Section
                label="calls"
                color="var(--success-fg)"
                Icon={TrendingUp}
                bullets={data.narrative.calls}
              />
            )}
            {data.narrative.puts.length > 0 && (
              <Section
                label="puts"
                color="var(--danger-fg)"
                Icon={TrendingDown}
                bullets={data.narrative.puts}
              />
            )}
            {data.narrative.risk.length > 0 && (
              <Section
                label="risk"
                color="var(--warning-fg)"
                Icon={ShieldAlert}
                bullets={data.narrative.risk}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Section({
  label,
  color,
  Icon,
  bullets,
}: {
  label: string;
  color: string;
  Icon: typeof TrendingUp;
  bullets: string[];
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon className="w-3 h-3" style={{ color }} />
        <span
          className="text-[10px] mono uppercase tracking-wider"
          style={{ color }}
        >
          {label}
        </span>
      </div>
      <ul className="space-y-1.5 text-xs leading-relaxed">
        {bullets.map((b, i) => (
          <li key={i} className="flex gap-1.5">
            <span className="mono" style={{ color }}>
              ›
            </span>
            <span>{b}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
