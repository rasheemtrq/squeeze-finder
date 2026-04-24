export function TableSkeleton({ rows = 10 }: { rows?: number }) {
  return (
    <div>
      <div className="flex items-end justify-between mb-3 px-1">
        <div className="space-y-1">
          <div className="h-3 w-28 bg-white/5 rounded" />
          <div className="h-4 w-40 bg-white/5 rounded" />
        </div>
        <div className="h-3 w-48 bg-white/5 rounded" />
      </div>
      <div className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
        <div className="h-10 border-b border-[var(--border)] bg-[var(--surface-2)]" />
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 px-3 py-3 border-b border-[var(--border)] last:border-b-0 animate-pulse"
          >
            <div className="h-3 w-6 bg-white/5 rounded" />
            <div className="h-3 w-16 bg-white/5 rounded" />
            <div className="h-3 w-14 bg-white/5 rounded ml-auto" />
            <div className="h-3 w-16 bg-white/5 rounded" />
            <div className="h-6 w-10 bg-white/5 rounded" />
            <div className="h-3 flex-1 bg-white/5 rounded" />
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-[var(--muted)] mono text-center">
        first scan pulls live data for the universe — may take 30-60s · subsequent scans cached
      </div>
    </div>
  );
}
