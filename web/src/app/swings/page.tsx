import { Suspense } from "react";
import { SwingTable } from "@/components/SwingTable";
import { TableSkeleton } from "@/components/TableSkeleton";

export const dynamic = "force-dynamic";

export default function SwingsPage() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-medium tracking-tight mb-2">
          swing-trade setups
        </h1>
        <p className="text-[var(--muted)] text-sm max-w-2xl">
          Multi-week trend continuation candidates &mdash; Stage&nbsp;2 trend
          (price &gt; 50EMA &gt; 200EMA), volume-confirmed breakout or OBV
          accumulation, relative strength vs SPY, near-term catalyst, and
          smart-money confirmation. Designed to catch INTC-style or SNDK-style
          moves early. Different scoring than the squeeze scan.
        </p>
      </div>

      <Suspense fallback={<TableSkeleton rows={15} />}>
        <SwingTable limit={25} />
      </Suspense>
    </div>
  );
}
