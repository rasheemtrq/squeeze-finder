"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import {
  fetchQuicktake,
  formatMarketCap,
  formatPrice,
  type Quicktake,
  type SwingResult,
} from "@/lib/api";
import { ScoreBadge, FactorBar } from "./ScoreBadge";
import { Flag } from "./Flag";
import { Logo } from "./Logo";
import { TakeButton, TakeExpansion } from "./ScanRow";

const FACTORS = ["stage2", "breakout", "rs", "catalyst", "smart_money"] as const;
const TOTAL_COLS = 13;

export function SwingRow({ r, index }: { r: SwingResult; index: number }) {
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
        {FACTORS.map((k) => (
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
        <tr className="border-b border-[var(--border)] last:border-b-0">
          <td colSpan={TOTAL_COLS} className="px-3 pb-3 pt-0">
            <TakeExpansion take={take} error={error} />
          </td>
        </tr>
      )}
    </>
  );
}
