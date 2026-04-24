import Link from "next/link";
import { Suspense } from "react";
import { ArrowLeft } from "lucide-react";
import { fetchTicker, formatMarketCap, formatPrice } from "@/lib/api";
import { ScoreBadge, FactorBar } from "@/components/ScoreBadge";
import { Flag } from "@/components/Flag";
import { NarrativeCard } from "@/components/NarrativeCard";
import { LogIdeaDialog } from "@/components/LogIdeaDialog";
import { Logo } from "@/components/Logo";
import { PriceChart } from "@/components/PriceChart";
import { OptionsRecommendations } from "@/components/OptionsRecommendations";

async function TickerDetail({ symbol }: { symbol: string }) {
  let data;
  try {
    data = await fetchTicker(symbol);
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">fetch failed</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
      </div>
    );
  }

  const f = data.factors;
  const weights = { sentiment: 0.25, options: 0.25, si: 0.25, ta: 0.15, catalyst: 0.1 };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <Logo ticker={data.ticker} size={48} />
          <div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-3xl font-medium tracking-tight mono">{data.ticker}</h1>
              <span className="text-sm text-[var(--muted)]">{data.name}</span>
            </div>
            <div className="flex items-center gap-4 mt-2 text-sm text-[var(--muted)] mono">
              <span>{formatPrice(data.price)}</span>
              <span>·</span>
              <span>{formatMarketCap(data.market_cap)} mcap</span>
              <span>·</span>
              <span>as_of {new Date(data.as_of).toLocaleString()}</span>
            </div>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <div className="text-right">
            <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)] mb-1">
              composite
            </div>
            <ScoreBadge score={data.score} size="lg" />
          </div>
          <div className="pt-5">
            <LogIdeaDialog ticker={data} />
          </div>
        </div>
      </div>

      {data.flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.flags.map((flag) => (
            <Flag key={flag} flag={flag} />
          ))}
        </div>
      )}

      <PriceChart symbol={data.ticker} />

      <OptionsRecommendations symbol={data.ticker} />

      <NarrativeCard symbol={data.ticker} />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
        {(["sentiment", "options", "si", "ta", "catalyst"] as const).map((k) => {
          const signals = f[k].signals as Record<string, unknown>;
          return (
            <div
              key={k}
              className="rounded-md ring-border bg-[var(--surface)] p-4 space-y-3"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
                    {k}
                  </div>
                  <div className="text-[10px] mono text-[var(--muted)]">
                    weight {(weights[k] * 100).toFixed(0)}%
                  </div>
                </div>
                <ScoreBadge score={f[k].score} size="sm" />
              </div>
              <FactorBar score={f[k].score} />
              <div className="space-y-1 text-[11px] mono">
                {Object.entries(signals)
                  .filter(([key]) => key !== "flag" && key !== "reason")
                  .map(([key, val]) => (
                    <div key={key} className="flex justify-between gap-2">
                      <span className="text-[var(--muted)]">{key}</span>
                      <span className="text-right tabular-nums truncate">
                        {typeof val === "object"
                          ? JSON.stringify(val)
                          : val == null
                            ? "–"
                            : String(val)}
                      </span>
                    </div>
                  ))}
                {signals.reason != null && (
                  <div className="italic text-[var(--muted)]">{String(signals.reason)}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {Object.keys(data.errors).length > 0 && (
        <div className="rounded-md ring-border bg-[var(--surface)] p-4">
          <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)] mb-2">
            data source errors
          </div>
          <div className="space-y-1 text-[11px] mono">
            {Object.entries(data.errors).map(([src, msg]) => (
              <div key={src} className="flex gap-2">
                <span className="text-[var(--danger-fg)] w-24">{src}</span>
                <span className="text-[var(--muted)]">{msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-md ring-border bg-[var(--surface-2)] p-4 text-xs text-[var(--muted)] leading-relaxed">
        <div className="mono uppercase tracking-wider text-[10px] mb-2">disclaimer</div>
        Not investment advice. Scoring is probability-ranked, not a prediction. Data is free-tier and
        may be stale (FINRA short interest is bi-monthly; yfinance caches are opaque). Bear case and
        invalidation must be reasoned about before action.
      </div>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="flex justify-between">
        <div className="space-y-2">
          <div className="h-8 w-24 bg-white/5 rounded" />
          <div className="h-3 w-56 bg-white/5 rounded" />
        </div>
        <div className="h-10 w-16 bg-white/5 rounded" />
      </div>
      <div className="h-48 rounded-md ring-border bg-[var(--surface)]" />
      <div className="grid grid-cols-5 gap-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="rounded-md ring-border bg-[var(--surface)] p-4 h-48" />
        ))}
      </div>
    </div>
  );
}

export default async function TickerPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-[var(--muted)] hover:text-white transition-colors mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        back to scan
      </Link>
      <Suspense fallback={<DetailSkeleton />}>
        <TickerDetail symbol={symbol.toUpperCase()} />
      </Suspense>
    </div>
  );
}
