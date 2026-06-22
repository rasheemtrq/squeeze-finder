"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  AreaSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
  PriceScaleMode,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import clsx from "clsx";
import { TrendingUp } from "lucide-react";
import { fetchChart, type ChartData } from "@/lib/api";

const VERCEL = {
  bg: "#0a0a0a",
  text: "#8f8f8f",
  grid: "rgba(255,255,255,0.04)",
  line: "#3b9eff",
  areaTop: "rgba(59,158,255,0.22)",
  areaBottom: "rgba(59,158,255,0.0)",
  entry: "#ededed",
  sl: "#f56e7d",
  tp: "#6ee787",
  poc: "#f5d16e",
  ladder: "rgba(110,231,135,0.45)",
};

const PERIODS = [
  { k: "1mo", label: "1M" },
  { k: "3mo", label: "3M" },
  { k: "6mo", label: "6M" },
  { k: "1y", label: "1Y" },
];

const PROJECTION_DAYS = 35; // ~5 weeks of "potential gains" trajectory

export function PriceChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<"Area"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const [data, setData] = useState<ChartData | null>(null);
  const [period, setPeriod] = useState("3mo");
  const [logScale, setLogScale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchChart(symbol, period)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [symbol, period]);

  useEffect(() => {
    if (!containerRef.current || !data) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 380,
      layout: {
        background: { color: VERCEL.bg },
        textColor: VERCEL.text,
        fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: VERCEL.grid },
        horzLines: { color: VERCEL.grid },
      },
      rightPriceScale: {
        borderColor: "#1f1f1f",
        mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
        scaleMargins: { top: 0.12, bottom: 0.18 },
      },
      timeScale: { borderColor: "#1f1f1f", timeVisible: false },
      crosshair: {
        vertLine: { color: "#404040", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "#404040", width: 1, style: LineStyle.Dashed },
      },
      autoSize: false,
    });
    chartRef.current = chart;

    const l = data.levels;
    const ladderMax = l.ladder.length ? Math.max(...l.ladder.map((t) => t.price)) : l.tp;

    // Price as a smooth area line, autoscaled to always include SL + TP.
    const price = chart.addSeries(AreaSeries, {
      lineColor: VERCEL.line,
      topColor: VERCEL.areaTop,
      bottomColor: VERCEL.areaBottom,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const res = original();
        if (!res || !res.priceRange) return res;
        const top = logScale ? ladderMax : l.tp;
        const minV = Math.min(res.priceRange.minValue, l.stop);
        const maxV = Math.max(res.priceRange.maxValue, top);
        const pad = (maxV - minV) * 0.04;
        return { priceRange: { minValue: minV - pad, maxValue: maxV + pad } };
      },
    });
    priceRef.current = price;

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: "rgba(143,143,143,0.30)",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volumeRef.current = volume;

    const toUTC = (ymd: string): UTCTimestamp =>
      (Math.floor(new Date(ymd + "T00:00:00Z").getTime() / 1000) as UTCTimestamp);

    price.setData(data.bars.map((b) => ({ time: toUTC(b.date), value: b.close })));
    volume.setData(
      data.bars.map((b) => ({
        time: toUTC(b.date),
        value: b.volume,
        color: b.close >= b.open ? "rgba(110,231,135,0.22)" : "rgba(245,110,125,0.22)",
      })),
    );

    // Dashed projection: today's price → TP, extended into the future. The
    // slope/length is the potential-gains trajectory.
    const lastBar = data.bars[data.bars.length - 1];
    const lastTime = toUTC(lastBar.date);
    const projTime = (lastTime + PROJECTION_DAYS * 86400) as UTCTimestamp;
    const projection = chart.addSeries(LineSeries, {
      color: VERCEL.tp,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    projection.setData([
      { time: lastTime, value: lastBar.close },
      { time: projTime, value: l.tp },
    ]);

    const addLine = (
      linePrice: number | null,
      color: string,
      title: string,
      style: LineStyle = LineStyle.Solid,
      width: 1 | 2 = 1,
    ) => {
      if (linePrice == null) return;
      price.createPriceLine({
        price: linePrice,
        color,
        lineWidth: width,
        lineStyle: style,
        axisLabelVisible: true,
        title,
      });
    };

    addLine(l.entry, VERCEL.entry, "entry", LineStyle.Solid, 1);
    addLine(l.stop, VERCEL.sl, "SL", LineStyle.Dashed, 2);
    addLine(l.tp, VERCEL.tp, "TP", LineStyle.Solid, 2);
    addLine(l.poc, VERCEL.poc, "POC", LineStyle.Dotted, 1); // most-volume level
    if (logScale) {
      l.ladder.forEach((t) => addLine(t.price, VERCEL.ladder, `${t.r}R`, LineStyle.Dotted, 1));
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, logScale]);

  const l = data?.levels;

  return (
    <div className="rounded-md ring-border bg-[var(--surface)] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-3.5 h-3.5 text-[var(--muted)]" />
          <span className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
            price · TP / SL · volume levels
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex gap-0.5 bg-[var(--surface-2)] rounded p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.k}
                onClick={() => setPeriod(p.k)}
                className={clsx(
                  "px-2 py-0.5 rounded text-[10px] mono transition-colors",
                  period === p.k
                    ? "bg-white/10 text-white"
                    : "text-[var(--muted)] hover:text-white",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setLogScale((v) => !v)}
            className={clsx(
              "px-2 py-0.5 rounded text-[10px] mono border transition-colors",
              logScale
                ? "bg-[var(--accent)]/15 border-[var(--accent)]/40 text-[var(--accent)]"
                : "border-[var(--border)] text-[var(--muted)] hover:text-white",
            )}
            title="toggle log scale to plot the R-multiple target ladder"
          >
            log
          </button>
        </div>
      </div>

      <div className="relative">
        {loading && (
          <div className="h-[380px] flex items-center justify-center">
            <div className="text-[10px] mono text-[var(--muted)] animate-pulse">
              loading price data...
            </div>
          </div>
        )}
        {error && (
          <div className="h-[380px] flex flex-col items-center justify-center gap-1">
            <div className="text-sm text-[var(--danger-fg)]">chart unavailable</div>
            <div className="text-[10px] mono text-[var(--muted)]">{error}</div>
          </div>
        )}
        {!loading && !error && data && (
          <div ref={containerRef} className="w-full" style={{ height: 380 }} />
        )}
      </div>

      {l && !loading && !error && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 border-t border-[var(--border)] bg-[var(--surface-2)] text-[10px] mono">
          <Level label="entry" value={l.entry} color={VERCEL.entry} />
          <Level label="SL" value={l.stop} color={VERCEL.sl} pct={-l.risk_pct} note={basisLabel(l.sl_basis)} />
          <Level label="TP" value={l.tp} color={VERCEL.tp} pct={l.tp_pct} note={basisLabel(l.tp_basis)} />
          {l.poc != null && <Level label="POC" value={l.poc} color={VERCEL.poc} note="most volume" />}
          <span className="ml-auto text-[var(--muted)]">
            R:R <span className="text-white tabular-nums">{l.rr.toFixed(1)}</span>
            <span className="mx-2 opacity-40">·</span>
            <span className="text-white">log</span> for R-ladder
          </span>
        </div>
      )}
    </div>
  );
}

function basisLabel(basis: string): string | undefined {
  if (basis === "volume_support" || basis === "volume_resistance") return "vol";
  if (basis === "atr_floor") return "atr";
  if (basis === "r_multiple") return "3R";
  return undefined;
}

function Level({
  label,
  value,
  color,
  pct,
  note,
}: {
  label: string;
  value: number;
  color: string;
  pct?: number;
  note?: string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-sm" style={{ background: color }} />
      <span className="text-[var(--muted)]">{label}</span>
      <span className="tabular-nums">${value.toFixed(2)}</span>
      {pct !== undefined && (
        <span className="tabular-nums" style={{ color: pct >= 0 ? VERCEL.tp : VERCEL.sl }}>
          {pct >= 0 ? "+" : ""}
          {pct.toFixed(0)}%
        </span>
      )}
      {note && <span className="text-[var(--muted)] opacity-60">{note}</span>}
    </span>
  );
}
