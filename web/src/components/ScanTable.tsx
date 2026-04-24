import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { fetchScan, formatMarketCap, formatPrice } from "@/lib/api";
import { ScoreBadge, FactorBar } from "./ScoreBadge";
import { Flag } from "./Flag";
import { Logo } from "./Logo";

export async function ScanTable({ limit = 20 }: { limit?: number }) {
  let data;
  try {
    data = await fetchScan({ limit });
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">scan failed</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
        <div className="text-[var(--muted)] text-xs mt-2">
          Is the API running? <span className="mono">uv run squeeze serve</span>
        </div>
      </div>
    );
  }

  const { results, as_of, scored, universe_size } = data;

  return (
    <div>
      <div className="flex items-end justify-between mb-3 px-1">
        <div>
          <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)]">
            top candidates
          </div>
          <div className="text-sm text-[var(--muted)] mono">
            {results.length}/{scored} scored · {universe_size} in universe
          </div>
        </div>
        <div className="text-[11px] mono text-[var(--muted)]">
          as_of {new Date(as_of).toLocaleString()}
        </div>
      </div>

      <div className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--surface-2)]">
            <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              <th className="text-left font-normal px-3 py-2.5 w-10">#</th>
              <th className="text-left font-normal px-3 py-2.5">ticker</th>
              <th className="text-right font-normal px-3 py-2.5">price</th>
              <th className="text-right font-normal px-3 py-2.5">mcap</th>
              <th className="text-right font-normal px-3 py-2.5">score</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">sent</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">opts</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">si</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">ta</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">cat</th>
              <th className="text-left font-normal px-3 py-2.5">flags</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {results.length === 0 && (
              <tr>
                <td colSpan={12} className="px-3 py-12 text-center text-sm text-[var(--muted)]">
                  no results — try lowering min_score
                </td>
              </tr>
            )}
            {results.map((r, i) => (
              <tr
                key={r.ticker}
                className="border-b border-[var(--border)] last:border-b-0 hover:bg-white/[0.02] transition-colors group"
              >
                <td className="px-3 py-3 mono tabular-nums text-[var(--muted)]">{i + 1}</td>
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
                <td className="px-3 py-3 text-right">
                  <Link
                    href={`/t/${r.ticker}`}
                    className="inline-flex items-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <ArrowUpRight className="w-4 h-4 text-[var(--muted)]" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
