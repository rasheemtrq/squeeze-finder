import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { fetchSwingScan, formatMarketCap, formatPrice } from "@/lib/api";
import { ScoreBadge, FactorBar } from "./ScoreBadge";
import { Flag } from "./Flag";
import { Logo } from "./Logo";
import { QuicktakeCell } from "./QuicktakeCell";

const FACTORS = ["stage2", "breakout", "rs", "catalyst", "smart_money"] as const;
const FACTOR_LABEL: Record<(typeof FACTORS)[number], string> = {
  stage2: "stage2",
  breakout: "vol/brk",
  rs: "rs vs spy",
  catalyst: "cat",
  smart_money: "smart $",
};

export async function SwingTable({ limit = 25 }: { limit?: number }) {
  let data;
  try {
    data = await fetchSwingScan({ limit });
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">swing scan failed</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
        <div className="text-[var(--muted)] text-xs mt-2">
          Is the API running? <span className="mono">uv run squeeze serve</span>
        </div>
      </div>
    );
  }

  const { results, as_of, scored, universe_size, cache_age_seconds, cache_stale, regime } = data;
  const ageLabel = cache_age_seconds == null
    ? null
    : cache_age_seconds < 60
      ? `${Math.round(cache_age_seconds)}s ago`
      : `${Math.round(cache_age_seconds / 60)}m ago`;

  return (
    <div>
      <div className="flex items-end justify-between mb-3 px-1">
        <div>
          <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)]">
            swing setups · stage 2 trend continuations
          </div>
          <div className="text-sm text-[var(--muted)] mono">
            {results.length}/{scored} scored · {universe_size} in universe
            {regime && (
              <> · regime <span className={regime.regime === "risk_off" ? "text-[var(--danger-fg)]" : ""}>{regime.regime}</span></>
            )}
          </div>
        </div>
        <div className="text-[11px] mono text-[var(--muted)] flex items-center gap-2">
          {ageLabel && (
            <span className={cache_stale ? "text-[var(--warning-fg)]" : ""}>
              {cache_stale ? "stale (refreshing) · " : "cached · "}
              {ageLabel}
            </span>
          )}
          <span>as_of {new Date(as_of).toLocaleString()}</span>
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
              {FACTORS.map((k) => (
                <th key={k} className="text-left font-normal px-3 py-2.5 w-[120px]">
                  {FACTOR_LABEL[k]}
                </th>
              ))}
              <th className="text-left font-normal px-3 py-2.5">flags</th>
              <th className="text-left font-normal px-3 py-2.5">take</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {results.length === 0 && (
              <tr>
                <td colSpan={13} className="px-3 py-12 text-center text-sm text-[var(--muted)]">
                  no setups passing min_score — universe may be in a chop regime
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
                <td className="px-3 py-3">
                  <QuicktakeCell ticker={r.ticker} />
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

      <div className="mt-3 text-[11px] text-[var(--muted)] mono px-1 leading-relaxed">
        composite weights: stage2 30 · breakout 25 · rs 20 · catalyst 15 · smart_money 10
      </div>
    </div>
  );
}
