"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Sparkles, Loader2 } from "lucide-react";
import {
  fetchQuicktake,
  formatMarketCap,
  formatPrice,
  type Quicktake,
  type TickerResult,
} from "@/lib/api";
import { ScoreBadge, FactorBar } from "./ScoreBadge";
import { Flag } from "./Flag";
import { Logo } from "./Logo";

const TOTAL_COLS = 13;

export function ScanRow({ r, index }: { r: TickerResult; index: number }) {
  const [take, setTake] = useState<Quicktake | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (take || loading) return;
    setLoading(true);
    setError(null);
    try {
      setTake(await fetchQuicktake(r.ticker));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const expanded = !!take || !!error;

  return (
    <>
      <tr
        className={
          "border-b border-[var(--border)] last:border-b-0 hover:bg-white/[0.02] transition-colors group " +
          (expanded ? "border-b-transparent" : "")
        }
      >
        <td className="px-3 py-3 mono tabular-nums text-[var(--muted)]">{index + 1}</td>
        <td className="px-3 py-3">
          <Link
            href={`/t/${r.ticker}`}
            className="flex items-center gap-2.5 group-hover:text-[var(--accent)] transition-colors"
          >
            <Logo ticker={r.ticker} size={26} />
            <div className="flex flex-col gap-0.5 min-w-0">
              <span className="mono font-medium text-sm">{r.ticker}</span>
              <span className="text-[11px] text-[var(--muted)] truncate max-w-[180px]">
                {r.name}
              </span>
            </div>
          </Link>
        </td>
        <td className="px-3 py-3 mono tabular-nums text-right">{formatPrice(r.price)}</td>
        <td className="px-3 py-3 mono tabular-nums text-right text-[var(--muted)]">
          {formatMarketCap(r.market_cap)}
        </td>
        <td className="px-3 py-3 text-right">
          <ScoreBadge score={r.score} size="md" />
        </td>
        {(["sentiment", "options", "si", "ta", "catalyst"] as const).map((k) => (
          <td key={k} className="px-3 py-3">
            <div className="flex items-center gap-2">
              <span className="mono tabular-nums text-xs w-7 text-right text-[var(--muted)]">
                {r.factors[k].score.toFixed(0)}
              </span>
              <FactorBar score={r.factors[k].score} />
            </div>
          </td>
        ))}
        <td className="px-3 py-3">
          <div className="flex flex-wrap gap-1 max-w-[200px]">
            {r.flags.slice(0, 3).map((f) => (
              <Flag key={f} flag={f} />
            ))}
            {r.flags.length > 3 && (
              <span className="mono text-[10px] text-[var(--muted)]">
                +{r.flags.length - 3}
              </span>
            )}
          </div>
        </td>
        <td className="px-3 py-3 whitespace-nowrap">
          <TakeButton loading={loading} done={!!take} error={!!error} onClick={load} />
        </td>
        <td className="px-3 py-3 text-right">
          <Link
            href={`/t/${r.ticker}`}
            className="inline-flex items-center opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <ArrowUpRight className="w-4 h-4 text-[var(--muted)]" />
          </Link>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-[var(--border)] last:border-b-0 bg-white/[0.025]">
          <td colSpan={TOTAL_COLS} className="px-6 py-3">
            <TakeExpansion take={take} error={error} />
          </td>
        </tr>
      )}
    </>
  );
}

export function TakeButton({
  loading,
  done,
  error,
  onClick,
}: {
  loading: boolean;
  done: boolean;
  error: boolean;
  onClick: (e: React.MouseEvent) => void;
}) {
  if (loading) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] mono text-[var(--muted)]">
        <Loader2 className="w-3 h-3 animate-spin" /> …
      </span>
    );
  }
  if (done || error) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
        <Sparkles className="w-2.5 h-2.5" /> {error ? "failed" : "ready"}
      </span>
    );
  }
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[10px] mono uppercase tracking-wider text-[var(--accent)] hover:text-white transition-colors px-1.5 py-0.5 rounded border border-[var(--accent)]/30 hover:bg-[var(--accent)]/10"
      title="Generate Haiku take (~2s, $0.001)"
    >
      <Sparkles className="w-2.5 h-2.5" />
      take
    </button>
  );
}

export function TakeExpansion({
  take,
  error,
}: {
  take: Quicktake | null;
  error: string | null;
}) {
  if (error) {
    return (
      <div className="text-xs text-[var(--danger-fg)] flex items-start gap-2">
        <Sparkles className="w-3 h-3 mt-0.5 shrink-0" />
        <span className="mono">take failed: {error}</span>
      </div>
    );
  }
  if (!take) return null;
  return (
    <div
      className="flex items-start gap-2.5 text-[13px] leading-relaxed text-[var(--foreground)]"
      style={{ maxWidth: "min(48rem, 100%)" }}
    >
      <Sparkles className="w-3.5 h-3.5 text-[var(--accent)] mt-0.5 shrink-0" />
      <span>{take.take}</span>
    </div>
  );
}
