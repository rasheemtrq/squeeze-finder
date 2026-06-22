import { Suspense } from "react";
import { ScanTable } from "@/components/ScanTable";
import { TableSkeleton } from "@/components/TableSkeleton";

export default function Home() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-medium tracking-tight mb-2">
          short-squeeze scanner
        </h1>
        <p className="text-[var(--muted)] text-sm max-w-2xl">
          Ranks US equities by a 5-factor composite targeting 2–10x squeeze setups.
          Sentiment (25), options/gamma (25), short interest (25), technicals (15),
          catalyst proximity (10). Free data sources only.
        </p>
      </div>

      <Suspense fallback={<TableSkeleton rows={12} />}>
        {/* Default to composite so the landing page always shows candidates.
            Pressure is a strict imminent-squeeze gate (lending+gamma+social) that
            is frequently empty — users can toggle to it from the table controls. */}
        <ScanTable limit={25} sort_by="composite" />
      </Suspense>
    </div>
  );
}
