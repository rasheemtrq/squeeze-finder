import { Suspense } from "react";
import { BigFishTable } from "@/components/BigFishTable";
import { TableSkeleton } from "@/components/TableSkeleton";

export const dynamic = "force-dynamic";

export default async function BigFishPage({
  searchParams,
}: {
  searchParams: Promise<{ sort?: string }>;
}) {
  const sp = await searchParams;
  const sortBy = sp?.sort ?? "dollar_volume";
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-medium tracking-tight mb-2">follow the big fish</h1>
          <p className="text-[var(--muted)] text-sm max-w-2xl">
            Market-wide volume leaders &mdash; where the money is actually trading. Ranked by
            dollar volume (shares &times; price) by default, so megacaps and index ETFs surface
            over low-price share churn and leveraged ETFs that top the raw-share list. Toggle to
            sort by raw shares, biggest move, or trade count.
          </p>
        </div>
        <a
          href="/"
          className="shrink-0 text-[10px] mono text-[var(--muted)] hover:text-white transition-colors"
        >
          ← squeeze scan
        </a>
      </div>

      <Suspense key={sortBy} fallback={<TableSkeleton rows={20} />}>
        <BigFishTable top={30} sortBy={sortBy} />
      </Suspense>
    </div>
  );
}
