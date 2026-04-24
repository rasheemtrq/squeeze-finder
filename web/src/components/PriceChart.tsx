"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineStyle,
  PriceScaleMode,
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
  up: "#6ee787",
  down: "#f56e7d",
  entry: "#ededed",
  stop: "#f56e7d",
  breakout: "#f5d16e",
  target2: "#6ee787",
  target5: "#3bd36f",
  target10: "#0070f3",
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
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
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

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: VERCEL.up,
      downColor: VERCEL.down,
      borderUpColor: VERCEL.up,
      borderDownColor: VERCEL.down,
      wickUpColor: VERCEL.up,
      wickDownColor: VERCEL.down,
    });
    candleRef.current = candles;

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: "rgba(143,143,143,0.35)",
    });
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });
    volumeRef.current = volume;

    const toUTC = (ymd: string): UTCTimestamp =>
      (Math.floor(new Date(ymd + "T00:00:00Z").getTime() / 1000) as UTCTimestamp);

    candles.setData(
      data.bars.map((b) => ({
        time: toUTC(b.date),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    volume.setData(
      data.bars.map((b) => ({
        time: toUTC(b.date),
        value: b.volume,
        color: b.close >= b.open ? "rgba(110,231,135,0.25)" : "rgba(245,110,125,0.25)",
      })),
    );

    const addLine = (price: number, color: string, title: string, dashed = false) => {
      candles.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title,
      });
    };

    const l = data.levels;
    addLine(l.entry, VERCEL.entry, "entry");
    addLine(l.stop, VERCEL.stop, "stop", true);
    addLine(l.breakout_60d, VERCEL.breakout, "60d high", true);
    addLine(l.target_2x, VERCEL.target2, "2×");
    if (logScale) {
      addLine(l.target_5x, VERCEL.target5, "5×");
      addLine(l.target_10x, VERCEL.target10, "10×");
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

  return (
    <div className="rounded-md ring-border bg-[var(--surface)] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-3.5 h-3.5 text-[var(--muted)]" />
          <span className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
            price · entry + projected targets
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
            title="toggle log scale to see 5× / 10× targets"
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
          <Level label="stop" value={data.levels.stop} color={VERCEL.stop} />
          <Level label="60d high" value={data.levels.breakout_60d} color={VERCEL.breakout} />
          <Level label="2×" value={data.levels.target_2x} color={VERCEL.target2} />
          <Level label="5×" value={data.levels.target_5x} color={VERCEL.target5} />
          <Level label="10×" value={data.levels.target_10x} color={VERCEL.target10} />
          {!logScale && (
            <span className="text-[var(--muted)] ml-auto">
              toggle <span className="text-white">log</span> to see 5× / 10× on chart
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function Level({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-sm" style={{ background: color }} />
      <span className="text-[var(--muted)]">{label}</span>
      <span className="tabular-nums">${value.toFixed(2)}</span>
    </span>
  );
}
