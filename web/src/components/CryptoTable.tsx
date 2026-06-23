import { type CryptoResult, fetchCryptoScan } from "@/lib/api";

function fmtPrice(p: number): string {
  if (p >= 1000) return `$${p.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (p >= 1) return `$${p.toFixed(2)}`;
  return `$${p.toPrecision(3)}`; // sub-dollar coins (DOGE, SHIB, XTZ…)
}

function scoreColor(s: number): string {
  if (s >= 55) return "#6ee787";
  if (s >= 35) return "#f5d16e";
  return "var(--muted)";
}

export async function CryptoTable({ limit = 25 }: { limit?: number }) {
  let data;
  try {
    data = await fetchCryptoScan({ limit });
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">crypto scan failed</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
        <div className="text-[var(--muted)] text-xs mt-2">
          Is the API running? <span className="mono">uv run squeeze serve</span>
        </div>
      </div>
    );
  }

  const { results, scored, universe } = data;

  return (
    <div>
      <div className="flex items-end justify-between mb-3 px-1">
        <div>
          <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)]">
            spot crypto · momentum (trend + breakout + RS vs BTC)
          </div>
          <div className="text-sm text-[var(--muted)] mono">
            {results.length}/{scored} scored · {universe} tradable pairs
          </div>
        </div>
        <div className="text-[11px] mono text-[var(--muted)]">
          score ≥ 55 = bot-tradable
        </div>
      </div>

      <div className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--surface-2)]">
            <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              <th className="text-left font-normal px-3 py-2.5 w-10">#</th>
              <th className="text-left font-normal px-3 py-2.5">pair</th>
              <th className="text-right font-normal px-3 py-2.5">price</th>
              <th className="text-right font-normal px-3 py-2.5">score</th>
              <th className="text-right font-normal px-3 py-2.5">trend</th>
              <th className="text-right font-normal px-3 py-2.5">brk</th>
              <th className="text-right font-normal px-3 py-2.5">rs/btc</th>
              <th className="text-right font-normal px-3 py-2.5">rvol</th>
              <th className="text-left font-normal px-3 py-2.5">entry → stop → tp</th>
              <th className="text-right font-normal px-3 py-2.5">R:R</th>
              <th className="text-left font-normal px-3 py-2.5">flags</th>
            </tr>
          </thead>
          <tbody>
            {results.length === 0 && (
              <tr>
                <td colSpan={11} className="px-3 py-12 text-center text-sm text-[var(--muted)]">
                  no coins scored — universe may be unavailable
                </td>
              </tr>
            )}
            {results.map((r, i) => (
              <Row key={r.ticker} r={r} index={i} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-[11px] text-[var(--muted)] mono px-1 leading-relaxed">
        composite weights: trend 30 · breakout 40 · rs-vs-btc 30 · spot long, 24/7 · stop &amp; tp
        from ATR / volume-profile levels · the paper bot trades pairs scoring ≥ 55
      </div>
    </div>
  );
}

function Row({ r, index }: { r: CryptoResult; index: number }) {
  const f = r.factors;
  const lv = r.levels;
  const flags = r.flags.filter((fl) => fl !== "asset:crypto");
  return (
    <tr className="border-b border-[var(--border)]/50 last:border-0 hover:bg-[var(--surface-2)]/50">
      <td className="px-3 py-2.5 text-[var(--muted)] mono text-xs">{index + 1}</td>
      <td className="px-3 py-2.5 font-medium mono">{r.ticker}</td>
      <td className="px-3 py-2.5 text-right mono text-xs">{fmtPrice(r.price)}</td>
      <td className="px-3 py-2.5 text-right mono tabular-nums font-medium" style={{ color: scoreColor(r.score) }}>
        {r.score.toFixed(0)}
      </td>
      <td className="px-3 py-2.5 text-right mono text-xs text-[var(--muted)]">{f.trend.score.toFixed(0)}</td>
      <td className="px-3 py-2.5 text-right mono text-xs text-[var(--muted)]">{f.breakout.score.toFixed(0)}</td>
      <td className="px-3 py-2.5 text-right mono text-xs text-[var(--muted)]">{f.rs_vs_btc.score.toFixed(0)}</td>
      <td className="px-3 py-2.5 text-right mono text-xs text-[var(--muted)]">
        {(f.breakout.rvol ?? 0).toFixed(1)}
      </td>
      <td className="px-3 py-2.5 text-left mono text-xs">
        <span>{fmtPrice(lv.entry)}</span>
        <span className="text-[var(--danger-fg)]"> → {fmtPrice(lv.stop)}</span>
        <span className="text-[#6ee787]"> → {fmtPrice(lv.tp)}</span>
      </td>
      <td className="px-3 py-2.5 text-right mono text-xs tabular-nums">{(lv.rr ?? 0).toFixed(1)}</td>
      <td className="px-3 py-2.5 text-left">
        <div className="flex flex-wrap gap-1">
          {flags.map((fl) => (
            <span
              key={fl}
              className="text-[9px] mono px-1.5 py-0.5 rounded bg-[var(--surface-2)] text-[var(--muted)]"
            >
              {fl}
            </span>
          ))}
        </div>
      </td>
    </tr>
  );
}
