"use client";

import { useState } from "react";

const SOURCES = (t: string) => [
  `https://logos.stocktwits-cdn.com/${t}.png`,
  `https://static2.finnhub.io/file/publicdatany/finnhubimage/stock_logo/${t}.png`,
];

export function Logo({ ticker, size = 24 }: { ticker: string; size?: number }) {
  const [attempt, setAttempt] = useState(0);
  const urls = SOURCES(ticker);

  if (attempt >= urls.length) {
    return (
      <div
        className="flex items-center justify-center rounded bg-white/[0.06] text-[var(--muted)] mono font-medium flex-shrink-0 ring-1 ring-[var(--border)]"
        style={{ width: size, height: size, fontSize: Math.max(10, size * 0.42) }}
      >
        {ticker[0]}
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={urls[attempt]}
      alt=""
      width={size}
      height={size}
      className="rounded bg-white/[0.03] flex-shrink-0 ring-1 ring-[var(--border)] object-contain"
      style={{ width: size, height: size }}
      onError={() => setAttempt((a) => a + 1)}
    />
  );
}
