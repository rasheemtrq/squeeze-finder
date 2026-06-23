import { Suspense } from "react";
import { CryptoTable } from "@/components/CryptoTable";
import { TableSkeleton } from "@/components/TableSkeleton";

export const dynamic = "force-dynamic";

export default function CryptoPage() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-medium tracking-tight mb-2">spot crypto momentum</h1>
          <p className="text-[var(--muted)] text-sm max-w-2xl">
            Liquid USD pairs ranked on momentum &mdash; trend stage (price &gt; 50EMA &gt;
            200EMA), volume-confirmed breakout, and relative strength versus Bitcoin. Crypto
            has no short interest or options gamma, so this is pure price/volume momentum,
            scored differently than the squeeze and swing scans. The paper bot trades spot
            (long-only, 24/7) on pairs scoring 55 or higher, sizing each position so a hit to
            the ATR/volume stop loses 1% of equity.
          </p>
        </div>
        <a
          href="/"
          className="shrink-0 text-[10px] mono text-[var(--muted)] hover:text-white transition-colors"
        >
          ← squeeze scan
        </a>
      </div>

      <Suspense fallback={<TableSkeleton rows={15} />}>
        <CryptoTable limit={25} />
      </Suspense>
    </div>
  );
}
