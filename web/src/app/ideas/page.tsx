import { Suspense } from "react";
import { IdeasTable } from "@/components/IdeasTable";

function Skeleton() {
  return (
    <div className="animate-pulse space-y-3">
      <div className="flex gap-6 px-1">
        <div className="h-3 w-16 bg-white/5 rounded" />
        <div className="h-3 w-28 bg-white/5 rounded" />
        <div className="h-3 w-20 bg-white/5 rounded" />
      </div>
      <div className="rounded-md ring-border bg-[var(--surface)]">
        <div className="h-10 border-b border-[var(--border)] bg-[var(--surface-2)]" />
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-14 border-b last:border-b-0 border-[var(--border)]" />
        ))}
      </div>
    </div>
  );
}

export default function IdeasPage() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-medium tracking-tight mb-2">ideas</h1>
        <p className="text-[var(--muted)] text-sm">
          Open, closed, and post-mortemed squeeze theses. Append-only log.
        </p>
      </div>
      <Suspense fallback={<Skeleton />}>
        <IdeasTable />
      </Suspense>
    </div>
  );
}
