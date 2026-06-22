"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  AreaSeries,
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
  tp1: "#6ee787",
  tp2: "#3bd36f",
  tp3: "#0070f3",
};

const PERIODS = [
  { k: "1mo", label: "1M" },
  { k: "3mo", label: "3M" },
  { k: "6mo", label: "6M" },
  { k: "1y", label: "1Y" },
];

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
      timeScale: {
        borderColor: "#1f1f1f",
        timeVisible: false,
      },
      crosshair: {
        vertLine: { color: "#404040", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "#404040", width: 1, style: LineStyle.Dashed },
      },
      autoSize: false,
    });
    chartRef.current = chart;

    // Smooth line (area) of close price — the "potential gains" path.
    const price = chart.addSeries(AreaSeries, {
      lineColor: VERCEL.line,
      topColor: VERCEL.areaTop,
      bottomColor: VERCEL.areaBottom,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      // Keep SL and the shown TP target inside the visible range so both
      // markers are always on-chart — the gap from price to TP reads as the
      // potential gain. (5×/10× only when log scale is on, else it crushes.)
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const res = original();
        if (!res || !res.priceRange) return res;
        const lv = data.levels;
        const highs = [res.priceRange.maxValue, lv.target_2x];
        if (logScale) highs.push(lv.target_5x, lv.target_10x);
        const minV = Math.min(res.priceRange.minValue, lv.stop);
        const maxV = Math.max(...highs);
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
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeRef.current = volume;

    const toUTC = (ymd: string): UTCTimestamp =>
      (Math.floor(new Date(ymd + "T00:00:00Z").getTime() / 1000) as UTCTimestamp);

    price.setData(
      data.bars.map((b) => ({ time: toUTC(b.date), value: b.close })),
    );
    volume.setData(
      data.bars.map((b) => ({
        time: toUTC(b.date),
        value: b.volume,
        color: b.close >= b.open ? "rgba(110,231,135,0.22)" : "rgba(245,110,125,0.22)",
      })),
    );

    const addLine = (
      linePrice: number,
      color: string,
      title: string,
      dashed = false,
      width: 1 | 2 = 1,
    ) => {
      price.createPriceLine({
        price: linePrice,
        color,
        lineWidth: width,
        lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title,
      });
    };

    const l = data.levels;
    // SL below, TP above — the markers the user trades against.
    addLine(l.entry, VERCEL.entry, "entry", false, 1);
    addLine(l.stop, VERCEL.sl, "SL", true, 2);
    addLine(l.target_2x, VERCEL.tp1, "TP", false, 2);
    if (logScale) {
      addLine(l.target_5x, VERCEL.tp2, "TP 5×");
      addLine(l.target_10x, VERCEL.tp3, "TP 10×");
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

  const entry = data?.levels.entry ?? 0;
  const pct = (v: number) => (entry > 0 ? ((v / entry - 1) * 100) : 0);

  return (
    <div className="rounded-md ring-border bg-[var(--surface)] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-3.5 h-3.5 text-[var(--muted)]" />
          <span className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
            price · TP / SL levels
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
            title="toggle log scale to see the 5× / 10× take-profit targets"
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

      {data && !loading && !error && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2.5 border-t border-[var(--border)] bg-[var(--surface-2)] text-[10px] mono">
          <Level label="entry" value={data.levels.entry} color={VERCEL.entry} />
          <Level label="SL" value={data.levels.stop} color={VERCEL.sl} pct={pct(data.levels.stop)} />
          <Level label="TP" value={data.levels.target_2x} color={VERCEL.tp1} pct={pct(data.levels.target_2x)} />
          <Level label="TP 5×" value={data.levels.target_5x} color={VERCEL.tp2} pct={pct(data.levels.target_5x)} />
          <Level label="TP 10×" value={data.levels.target_10x} color={VERCEL.tp3} pct={pct(data.levels.target_10x)} />
          {!logScale && (
            <span className="text-[var(--muted)] ml-auto">
              toggle <span className="text-white">log</span> to plot 5× / 10× TP
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function Level({
  label,
  value,
  color,
  pct,
}: {
  label: string;
  value: number;
  color: string;
  pct?: number;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-sm" style={{ background: color }} />
      <span className="text-[var(--muted)]">{label}</span>
      <span className="tabular-nums">${value.toFixed(2)}</span>
      {pct !== undefined && (
        <span
          className="tabular-nums"
          style={{ color: pct >= 0 ? VERCEL.tp1 : VERCEL.sl }}
        >
          {pct >= 0 ? "+" : ""}
          {pct.toFixed(0)}%
        </span>
      )}
    </span>
  );
}
