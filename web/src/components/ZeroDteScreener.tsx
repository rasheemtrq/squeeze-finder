import { fetchZeroDte, type ZeroDteContract } from "@/lib/api";
import { Logo } from "./Logo";
import { ZeroDteNarrativeCard } from "./ZeroDteNarrative";

const BLOCKED_COPY: Record<string, string> = {
  closed: "US equity market is closed. 0DTE chains only refresh during RTH.",
  pre_open: "Pre-market. The 0DTE screener wakes up after the 9:30a ET open.",
  auction_noise: "Inside the opening-auction window. Quotes are unstable until 9:45a ET.",
  midday_chop: "After 1:00p ET — Reddit-corpus consensus: 0DTE edge concentrates in the first 2-3 hours. Midday is chop where theta dominates.",
  theta_cliff: "After 3:30p ET — theta dominates the last 30 min. Screener is parked.",
};

function pct(v: number | null | undefined): string {
  if (v == null) return "–";
  return `${(v * 100).toFixed(1)}%`;
}

function formatProb(p: number): string {
  if (p >= 0.10) return `${(p * 100).toFixed(0)}%`;
  if (p >= 0.01) return `${(p * 100).toFixed(1)}%`;
  if (p > 0) return `${(p * 100).toFixed(2)}%`;
  return "0%";
}

function probColor(p: number): string {
  if (p >= 0.20) return "text-[var(--success-fg)]";
  if (p >= 0.05) return "text-[var(--warning-fg)]";
  return "text-[var(--muted)]";
}

function formatPrice(p: number | null | undefined): string {
  if (p == null) return "–";
  if (p >= 100) return `$${p.toFixed(0)}`;
  return `$${p.toFixed(2)}`;
}

function ContractRow({ c }: { c: ZeroDteContract }) {
  const dirColor =
    c.side === "call" ? "text-[var(--success-fg)]" : "text-[var(--danger-fg)]";
  return (
    <tr className="border-b border-[var(--border)] last:border-b-0 hover:bg-white/[0.02] transition-colors">
      <td className="px-3 py-2.5 mono">
        <span className={dirColor}>{c.side.toUpperCase()}</span>
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right">
        ${c.strike.toFixed(c.strike >= 100 ? 0 : 2)}
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right">
        ${c.mid.toFixed(2)}
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--muted)]">
        {c.delta.toFixed(2)}
      </td>
      <td className={`px-3 py-2.5 mono tabular-nums text-right ${probColor(c.p_2x)}`}>
        {formatProb(c.p_2x)}
      </td>
      <td className={`px-3 py-2.5 mono tabular-nums text-right ${probColor(c.p_5x)}`}>
        {formatProb(c.p_5x)}
      </td>
      <td className={`px-3 py-2.5 mono tabular-nums text-right ${probColor(c.p_10x)}`}>
        {formatProb(c.p_10x)}
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right">
        <div className="text-[var(--success-fg)]">{formatPrice(c.tp1_spot)}</div>
        <div className="text-[10px] text-[var(--muted)]">${c.tp1_price.toFixed(2)}</div>
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right">
        <div className="text-[var(--success-fg)]">{formatPrice(c.tp2_spot)}</div>
        <div className="text-[10px] text-[var(--muted)]">${c.tp2_price.toFixed(2)}</div>
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right">
        <div className="text-[var(--success-fg)]">{formatPrice(c.tp3_spot)}</div>
        <div className="text-[10px] text-[var(--muted)]">${c.tp3_price.toFixed(2)}</div>
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right">
        <div className="text-[var(--danger-fg)]">{formatPrice(c.sl_spot)}</div>
        <div className="text-[10px] text-[var(--muted)]">${c.sl_price.toFixed(2)}</div>
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--muted)]">
        {pct(c.expected_move_pct)}
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--muted)]">
        {c.volume.toLocaleString()}
      </td>
      <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--accent)]">
        {c.score.toFixed(1)}
      </td>
    </tr>
  );
}

export async function ZeroDteScreener() {
  let data;
  try {
    data = await fetchZeroDte();
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">screener failed</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
        <div className="text-[var(--muted)] text-xs mt-2">
          Is the API running? <span className="mono">uv run squeeze serve</span>
        </div>
      </div>
    );
  }

  if (!data.ok) {
    const reason = data.blocked_reason ?? "closed";
    return (
      <div className="rounded-md border border-[var(--warning)]/40 bg-[var(--warning)]/10 p-6 text-sm">
        <div className="text-[var(--warning-fg)] font-medium mb-1 mono uppercase tracking-wider text-xs">
          screener parked · {reason}
        </div>
        <div className="text-[var(--muted)] mt-2">
          {BLOCKED_COPY[reason] ?? "Outside the screener's active window."}
        </div>
        <div className="mt-4 text-[var(--muted)] text-xs">
          Universe: <span className="mono">{data.universe.join(" · ")}</span>
        </div>
      </div>
    );
  }

  const { results, as_of, expiry } = data;
  const totalContracts = results.reduce((n, r) => n + r.calls.length + r.puts.length, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between px-1">
        <div>
          <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)]">
            ranked 0dte contracts
          </div>
          <div className="text-sm text-[var(--muted)] mono">
            {totalContracts} contracts across {results.length} tickers · expiry {expiry}
          </div>
        </div>
        <div className="text-[11px] mono text-[var(--muted)]">
          as_of {new Date(as_of).toLocaleTimeString()}
        </div>
      </div>

      {results.length === 0 && (
        <div className="rounded-md ring-border bg-[var(--surface)] p-8 text-center text-sm text-[var(--muted)]">
          no contracts passed liquidity gates · check back when chains warm up
        </div>
      )}

      {results.map((r) => (
        <div key={r.ticker} className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] bg-[var(--surface-2)]">
            <div className="flex items-center gap-3">
              <Logo ticker={r.ticker} size={26} />
              <div>
                <div className="mono text-sm font-medium">{r.ticker}</div>
                <div className="text-[11px] text-[var(--muted)] mono">
                  spot ${r.spot.toFixed(2)} · {r.hours_until_close.toFixed(1)}h to close
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {r.chain_stale && (
                <span className="text-[10px] mono uppercase tracking-wider text-[var(--warning-fg)] bg-[var(--warning)]/10 px-2 py-1 rounded">
                  stale chain
                </span>
              )}
              <ZeroDteNarrativeCard ticker={r.ticker} />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-[var(--border)]">
                <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
                  <th className="text-left font-normal px-3 py-2.5">side</th>
                  <th className="text-right font-normal px-3 py-2.5">strike</th>
                  <th className="text-right font-normal px-3 py-2.5">mid</th>
                  <th className="text-right font-normal px-3 py-2.5">Δ</th>
                  <th className="text-right font-normal px-3 py-2.5">p(2x)</th>
                  <th className="text-right font-normal px-3 py-2.5">p(5x)</th>
                  <th className="text-right font-normal px-3 py-2.5">p(10x)</th>
                  <th className="text-right font-normal px-3 py-2.5">tp1 spot</th>
                  <th className="text-right font-normal px-3 py-2.5">tp2 spot</th>
                  <th className="text-right font-normal px-3 py-2.5">tp3 spot</th>
                  <th className="text-right font-normal px-3 py-2.5">sl spot</th>
                  <th className="text-right font-normal px-3 py-2.5">exp move</th>
                  <th className="text-right font-normal px-3 py-2.5">vol</th>
                  <th className="text-right font-normal px-3 py-2.5">score</th>
                </tr>
              </thead>
              <tbody>
                {[...r.calls, ...r.puts].map((c) => (
                  <ContractRow key={`${c.side}-${c.strike}`} c={c} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <div className="text-[11px] text-[var(--muted)] mono px-1 leading-relaxed space-y-1">
        <div>
          score = 1·P(2x) + 2·P(5x) + 3·P(10x), scaled ×100 · probabilities derived from chain IV
        </div>
        <div>
          tp1 = +50% mid (trim) · tp2 = +200% (trim more) · tp3 = +400% (runner) · sl = -50% mid · spot levels solved via Black-Scholes
        </div>
      </div>
    </div>
  );
}
