import { Suspense } from "react";
import { ZeroDteScreener } from "@/components/ZeroDteScreener";
import { TableSkeleton } from "@/components/TableSkeleton";

export const dynamic = "force-dynamic";

export default function ZeroDtePage() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-medium tracking-tight mb-2">
          0DTE lottery screener
        </h1>
        <p className="text-[var(--muted)] text-sm max-w-2xl">
          Same-day-expiry calls and puts on major-index ETFs and the most-liquid
          mega-caps, ranked by realistic 2x / 5x / 10x payoff probability under
          IV-implied move distribution. Active during RTH 9:45a&ndash;3:30p ET only.
        </p>
      </div>

      <Suspense fallback={<TableSkeleton rows={10} />}>
        <ZeroDteScreener />
      </Suspense>
    </div>
  );
}
