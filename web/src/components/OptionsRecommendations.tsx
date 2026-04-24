"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Zap, Info, Wallet } from "lucide-react";
import { fetchOptions, type OptionsRec, type OptionContract } from "@/lib/api";

type Sizing = {
  contracts: number;
  actualCost: number;
  unused: number;
  maxLoss: number;
  pnl: (targetSpot: number) => { value: number; profit: number; roi: number };
};

function computeSizing(c: OptionContract, capital: number): Sizing {
  const contracts = Math.max(0, Math.floor(capital / Math.max(c.cost_per_contract, 0.01)));
  const actualCost = contracts * c.cost_per_contract;
  const unused = Math.max(0, capital - actualCost);
  return {
    contracts,
    actualCost,
    unused,
    maxLoss: actualCost,
    pnl: (targetSpot: number) => {
      const intrinsic = Math.max(0, targetSpot - c.strike);
      const value = intrinsic * 100 * contracts;
      const profit = value - actualCost;
      const roi = actualCost > 0 ? profit / actualCost : 0;
      return { value, profit, roi };
    },
  };
}

function fmtMoney(n: number): string {
  if (!isFinite(n)) return "–";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${sign}$${(abs / 1000).toFixed(1)}K`;
  if (abs >= 1000) return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtMultiple(roi: number): string {
  if (!isFinite(roi)) return "–";
  const mult = 1 + roi;
  if (mult >= 100) return `${mult.toFixed(0)}×`;
  if (mult >= 10) return `${mult.toFixed(1)}×`;
  if (mult >= 2) return `${mult.toFixed(2)}×`;
  if (roi >= 0) return `+${(roi * 100).toFixed(0)}%`;
  return `${(roi * 100).toFixed(0)}%`;
}

const CAPITAL_KEY = "squeeze-finder:capital";

export function OptionsRecommendations({ symbol }: { symbol: string }) {
  const [data, setData] = useState<OptionsRec | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [capital, setCapital] = useState(1000);
  const [capitalInput, setCapitalInput] = useState("1000");

  useEffect(() => {
    try {
      const saved = typeof window !== "undefined" ? localStorage.getItem(CAPITAL_KEY) : null;
      if (saved) {
        const n = Number(saved);
        if (!Number.isNaN(n) && n > 0) {
          setCapital(n);
          setCapitalInput(String(n));
        }
      }
    } catch {}
  }, []);

  function commitCapital(v: string) {
    const n = Number(v.replace(/[,$\s]/g, ""));
    if (Number.isNaN(n) || n <= 0) {
      setCapitalInput(String(capital));
      return;
    }
    setCapital(n);
    setCapitalInput(String(n));
    try {
      localStorage.setItem(CAPITAL_KEY, String(n));
    } catch {}
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchOptions(symbol, 8)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return (
    <div className="rounded-md ring-border bg-[var(--surface)] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Zap className="w-3.5 h-3.5 text-[var(--accent)]" />
          <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
            options · squeeze-play recommendations
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
            <Wallet className="w-3 h-3" />
            capital
          </label>
          <div className="flex items-center gap-1">
            <span className="text-[var(--muted)] mono text-xs">$</span>
            <input
              value={capitalInput}
              onChange={(e) => setCapitalInput(e.target.value)}
              onBlur={(e) => commitCapital(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              className="w-24 bg-[var(--background)] ring-border rounded px-2 py-1 mono text-xs outline-none focus:ring-white/40 tabular-nums"
              inputMode="numeric"
            />
          </div>
          {data && (
            <div className="text-[10px] mono text-[var(--muted)]">
              spot ${data.spot.toFixed(2)} · {data.candidates_total} candidates
            </div>
          )}
        </div>
      </div>

      {loading && (
        <div className="h-48 flex items-center justify-center">
          <div className="text-[10px] mono text-[var(--muted)] animate-pulse">
            pulling option chain + computing greeks...
          </div>
        </div>
      )}

      {error && (
        <div className="h-48 flex flex-col items-center justify-center gap-1 px-6 text-center">
          <div className="text-sm text-[var(--danger-fg)]">options unavailable</div>
          <div className="text-[10px] mono text-[var(--muted)]">{error}</div>
        </div>
      )}

      {data && !loading && !error && (
        <>
          {data.recommendations.length === 0 && (
            <div className="h-48 flex flex-col items-center justify-center gap-1 text-center">
              <div className="text-sm">no viable contracts</div>
              <div className="text-[10px] mono text-[var(--muted)]">
                no calls passed filters (14–45 DTE, OI ≥ 50, spread ≤ 25%, Δ 0.10–0.60)
              </div>
            </div>
          )}

          {data.recommendations.length > 0 && (
            <>
              <RecommendationCards
                contracts={data.recommendations.slice(0, 3)}
                spot={data.spot}
                capital={capital}
              />

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-t border-b border-[var(--border)] bg-[var(--surface-2)]">
                    <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
                      <th className="text-left font-normal px-3 py-2.5">#</th>
                      <th className="text-left font-normal px-3 py-2.5">expiry</th>
                      <th className="text-right font-normal px-3 py-2.5">strike</th>
                      <th className="text-right font-normal px-3 py-2.5">mid</th>
                      <th className="text-right font-normal px-3 py-2.5">contracts</th>
                      <th className="text-right font-normal px-3 py-2.5">cost</th>
                      <th className="text-right font-normal px-3 py-2.5">Δ</th>
                      <th className="text-right font-normal px-3 py-2.5">γ</th>
                      <th className="text-right font-normal px-3 py-2.5">θ/d</th>
                      <th className="text-right font-normal px-3 py-2.5">IV</th>
                      <th className="text-right font-normal px-3 py-2.5">OI</th>
                      <th className="text-right font-normal px-3 py-2.5">BE</th>
                      <th className="text-right font-normal px-3 py-2.5">@2×</th>
                      <th className="text-right font-normal px-3 py-2.5">@5×</th>
                      <th className="text-right font-normal px-3 py-2.5">@10×</th>
                      <th className="text-right font-normal px-3 py-2.5">score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recommendations.map((c, i) => {
                      const s = computeSizing(c, capital);
                      const p2 = s.pnl(data.spot * 2);
                      const p5 = s.pnl(data.spot * 5);
                      const p10 = s.pnl(data.spot * 10);
                      return (
                        <tr
                          key={`${c.expiry}-${c.strike}`}
                          className={clsx(
                            "border-b border-[var(--border)] last:border-b-0 hover:bg-white/[0.02]",
                            i === 0 && "bg-[var(--accent)]/[0.04]",
                          )}
                        >
                          <td className="px-3 py-2.5 mono tabular-nums text-[var(--muted)]">
                            {i + 1}
                          </td>
                          <td className="px-3 py-2.5">
                            <div className="flex flex-col">
                              <span className="mono tabular-nums text-xs">{c.expiry}</span>
                              <span className="mono text-[10px] text-[var(--muted)]">
                                {c.dte}d
                              </span>
                            </div>
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <div className="flex flex-col items-end">
                              <span className="mono tabular-nums">${c.strike.toFixed(2)}</span>
                              <span className="mono text-[10px] text-[var(--muted)]">
                                {c.pct_otm >= 0 ? "+" : ""}
                                {(c.pct_otm * 100).toFixed(1)}%
                              </span>
                            </div>
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right font-medium">
                            ${c.mid.toFixed(2)}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right">
                            {s.contracts}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right">
                            {fmtMoney(s.actualCost)}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right">
                            {c.delta.toFixed(2)}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--muted)]">
                            {c.gamma?.toFixed(3) ?? "–"}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--danger-fg)]">
                            {c.theta?.toFixed(2) ?? "–"}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--muted)]">
                            {(c.iv * 100).toFixed(0)}%
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right text-[var(--muted)]">
                            {c.open_interest.toLocaleString()}
                          </td>
                          <td className="px-3 py-2.5 mono tabular-nums text-right">
                            ${c.breakeven.toFixed(2)}
                          </td>
                          <PnLCell p={p2} />
                          <PnLCell p={p5} />
                          <PnLCell p={p10} />
                          <td className="px-3 py-2.5 mono tabular-nums text-right font-medium">
                            {c.score.toFixed(0)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="px-4 py-3 border-t border-[var(--border)] bg-[var(--surface-2)] text-[10px] text-[var(--muted)] leading-relaxed space-y-1">
                <div className="flex items-start gap-1.5">
                  <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <div>
                    <span className="text-white">@2×/@5×/@10×</span> = intrinsic profit if spot hits
                    that multiple <em>at expiry</em>. If hit earlier, real value is typically higher
                    due to remaining time value and IV expansion during squeezes. Max loss = premium
                    paid = <span className="text-white">${capital.toLocaleString()}</span> (or less
                    if cost &lt; capital). Greeks via Black-Scholes; prices are yfinance mid — verify
                    at your broker before entry.
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function PnLCell({ p }: { p: { profit: number; roi: number } }) {
  const pos = p.profit > 0;
  return (
    <td
      className={clsx(
        "px-3 py-2.5 mono tabular-nums text-right",
        pos ? "text-[var(--success-fg)]" : "text-[var(--muted)]",
      )}
    >
      <div className="flex flex-col items-end">
        <span>{pos ? "+" : ""}{fmtMoney(p.profit)}</span>
        <span className="text-[10px] opacity-70">{fmtMultiple(p.roi)}</span>
      </div>
    </td>
  );
}

function RecommendationCards({
  contracts,
  spot,
  capital,
}: {
  contracts: OptionContract[];
  spot: number;
  capital: number;
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-0 border-b border-[var(--border)]">
      {contracts.slice(0, 3).map((c, i) => {
        const s = computeSizing(c, capital);
        const p2 = s.pnl(spot * 2);
        const p5 = s.pnl(spot * 5);
        const p10 = s.pnl(spot * 10);
        return (
          <div
            key={`${c.expiry}-${c.strike}`}
            className={clsx(
              "p-4 space-y-3",
              i < 2 && "md:border-r border-[var(--border)]",
              i === 0 && "bg-[var(--accent)]/[0.05]",
            )}
          >
            <div className="flex items-center justify-between">
              <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
                {i === 0 ? "top pick" : "alt"}
              </div>
              <div className="mono text-[10px] text-[var(--muted)]">score {c.score.toFixed(0)}</div>
            </div>

            <div>
              <div className="mono text-base font-medium tabular-nums">
                {c.ticker} ${c.strike.toFixed(2)} C
              </div>
              <div className="mono text-[11px] text-[var(--muted)]">
                exp {c.expiry} · {c.dte}d · {c.rationale.split(" · ").slice(0, 2).join(" · ")}
              </div>
            </div>

            <div className="flex gap-4 items-baseline">
              <div>
                <div className="text-[10px] mono uppercase text-[var(--muted)]">premium</div>
                <div className="mono text-xl tabular-nums">${c.mid.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-[10px] mono uppercase text-[var(--muted)]">per ct</div>
                <div className="mono text-xl tabular-nums">${c.cost_per_contract.toFixed(0)}</div>
              </div>
            </div>

            <div className="pt-2 border-t border-[var(--border)] space-y-1 text-[11px] mono">
              <div className="flex justify-between">
                <span className="text-[var(--muted)]">contracts to buy</span>
                <span className="tabular-nums font-medium">
                  {s.contracts} for {fmtMoney(s.actualCost)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--muted)]">max loss</span>
                <span className="tabular-nums text-[var(--danger-fg)]">
                  {fmtMoney(s.maxLoss)}
                </span>
              </div>
              {s.unused > 0.5 && (
                <div className="flex justify-between text-[10px] opacity-70">
                  <span className="text-[var(--muted)]">unused cash</span>
                  <span className="tabular-nums">{fmtMoney(s.unused)}</span>
                </div>
              )}
            </div>

            <div className="pt-2 border-t border-[var(--border)] space-y-1">
              <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
                if spot hits (at expiry)
              </div>
              <Row
                label={`2× · $${(spot * 2).toFixed(2)}`}
                profit={p2.profit}
                roi={p2.roi}
              />
              <Row
                label={`5× · $${(spot * 5).toFixed(2)}`}
                profit={p5.profit}
                roi={p5.roi}
              />
              <Row
                label={`10× · $${(spot * 10).toFixed(2)}`}
                profit={p10.profit}
                roi={p10.roi}
              />
            </div>

            <div className="pt-2 border-t border-[var(--border)] text-[11px] mono flex justify-between">
              <span className="text-[var(--muted)]">breakeven</span>
              <span>
                ${c.breakeven.toFixed(2)}{" "}
                <span className="text-[var(--muted)]">
                  (+{(c.breakeven_pct_from_spot * 100).toFixed(1)}%)
                </span>
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Row({ label, profit, roi }: { label: string; profit: number; roi: number }) {
  const pos = profit > 0;
  return (
    <div className="flex justify-between items-center text-[11px] mono">
      <span className="text-[var(--muted)]">{label}</span>
      <span className={clsx("tabular-nums flex gap-2", pos ? "text-[var(--success-fg)]" : "text-[var(--muted)]")}>
        <span className="font-medium">
          {pos ? "+" : ""}
          {fmtMoney(profit)}
        </span>
        <span className="opacity-70 text-[10px]">{fmtMultiple(roi)}</span>
      </span>
    </div>
  );
}
