import { type BigFishRow, fetchBigFish } from "@/lib/api";

const SORTS: { key: string; label: string }[] = [
  { key: "dollar_volume", label: "$ volume" },
  { key: "volume", label: "shares" },
  { key: "change", label: "move" },
  { key: "trades", label: "trades" },
];

function fmtUsd(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

function fmtShares(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  return n.toLocaleString();
}

export async function BigFishTable({ top = 30, sortBy = "dollar_volume" }: { top?: number; sortBy?: string }) {
  let data;
  try {
    data = await fetchBigFish({ top, sort_by: sortBy });
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">big fish unavailable</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
        <div className="text-[var(--muted)] text-xs mt-2">
          Needs Alpaca keys (data API). Is the API running?
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-end justify-between mb-3 px-1">
        <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)]">
          market-wide volume leaders · {data.count} most-active
        </div>
        <div className="flex gap-0.5 bg-[var(--surface-2)] rounded p-0.5 text-[10px] mono">
          {SORTS.map((s) => (
            <a
              key={s.key}
              href={`/big-fish?sort=${s.key}`}
              className={
                "px-2 py-0.5 rounded transition-colors " +
                (data.sort_by === s.key ? "bg-white/10 text-white" : "text-[var(--muted)] hover:text-white")
              }
            >
              {s.label}
            </a>
          ))}
        </div>
      </div>

      <div className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--surface-2)]">
            <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              <th className="text-left font-normal px-3 py-2.5 w-10">#</th>
              <th className="text-left font-normal px-3 py-2.5">symbol</th>
              <th className="text-right font-normal px-3 py-2.5">$ volume</th>
              <th className="text-right font-normal px-3 py-2.5">shares</th>
              <th className="text-right font-normal px-3 py-2.5">price</th>
              <th className="text-right font-normal px-3 py-2.5">chg %</th>
              <th className="text-right font-normal px-3 py-2.5">trades</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-12 text-center text-sm text-[var(--muted)]">
                  no data — market data unavailable
                </td>
              </tr>
            )}
            {data.rows.map((r, i) => (
              <Row key={r.symbol} r={r} index={i} sortBy={data.sort_by} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-[11px] text-[var(--muted)] mono px-1 leading-relaxed">
        ranked by {SORTS.find((s) => s.key === data.sort_by)?.label ?? data.sort_by} · $ volume = shares × price
        (the real big fish, vs low-price share churn) · source: Alpaca most-active screener
      </div>
    </div>
  );
}

function Row({ r, index, sortBy }: { r: BigFishRow; index: number; sortBy: string }) {
  const up = r.change_pct >= 0;
  const hot = (col: string) => (col === sortBy ? "text-white" : "text-[var(--muted)]");
  return (
    <tr className="border-b border-[var(--border)]/50 last:border-0 hover:bg-[var(--surface-2)]/50">
      <td className="px-3 py-2.5 text-[var(--muted)] mono text-xs">{index + 1}</td>
      <td className="px-3 py-2.5 font-medium mono">{r.symbol}</td>
      <td className={`px-3 py-2.5 text-right mono tabular-nums ${hot("dollar_volume")}`}>{fmtUsd(r.dollar_volume)}</td>
      <td className={`px-3 py-2.5 text-right mono text-xs tabular-nums ${hot("volume")}`}>{fmtShares(r.volume)}</td>
      <td className="px-3 py-2.5 text-right mono text-xs">${r.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
      <td className="px-3 py-2.5 text-right mono text-xs tabular-nums" style={{ color: up ? "#6ee787" : "#f56e7d" }}>
        {up ? "+" : ""}{r.change_pct.toFixed(1)}%
      </td>
      <td className={`px-3 py-2.5 text-right mono text-xs tabular-nums ${hot("trades")}`}>{r.trade_count.toLocaleString()}</td>
    </tr>
  );
}
