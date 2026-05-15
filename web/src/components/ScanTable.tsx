import { fetchScan } from "@/lib/api";
import { ScanRow } from "./ScanRow";

export async function ScanTable({ limit = 20 }: { limit?: number }) {
  let data;
  try {
    data = await fetchScan({ limit });
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">scan failed</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
        <div className="text-[var(--muted)] text-xs mt-2">
          Is the API running? <span className="mono">uv run squeeze serve</span>
        </div>
      </div>
    );
  }

  const { results, as_of, scored, universe_size, cache_age_seconds, cache_stale } = data;
  const ageLabel = cache_age_seconds == null
    ? null
    : cache_age_seconds < 60
      ? `${Math.round(cache_age_seconds)}s ago`
      : `${Math.round(cache_age_seconds / 60)}m ago`;

  return (
    <div>
      <div className="flex items-end justify-between mb-3 px-1">
        <div>
          <div className="text-[11px] mono uppercase tracking-wider text-[var(--muted)]">
            top candidates
          </div>
          <div className="text-sm text-[var(--muted)] mono">
            {results.length}/{scored} scored · {universe_size} in universe
          </div>
        </div>
        <div className="text-[11px] mono text-[var(--muted)] flex items-center gap-2">
          {ageLabel && (
            <span className={cache_stale ? "text-[var(--warning-fg)]" : ""}>
              {cache_stale ? "stale (refreshing) · " : "cached · "}
              {ageLabel}
            </span>
          )}
          <span>as_of {new Date(as_of).toLocaleString()}</span>
        </div>
      </div>

      <div className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--surface-2)]">
            <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              <th className="text-left font-normal px-3 py-2.5 w-10">#</th>
              <th className="text-left font-normal px-3 py-2.5">ticker</th>
              <th className="text-right font-normal px-3 py-2.5">price</th>
              <th className="text-right font-normal px-3 py-2.5">mcap</th>
              <th className="text-right font-normal px-3 py-2.5">score</th>
              <th
                className="text-right font-normal px-3 py-2.5"
                title="multiplicative squeeze pressure (lending × gamma × social, geometric mean). all three must fire."
              >
                pressure
              </th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">sent</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">opts</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">si</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">ta</th>
              <th className="text-left font-normal px-3 py-2.5 w-[120px]">cat</th>
              <th className="text-left font-normal px-3 py-2.5">flags</th>
              <th className="text-left font-normal px-3 py-2.5 w-[80px]">take</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {results.length === 0 && (
              <tr>
                <td colSpan={14} className="px-3 py-12 text-center text-sm text-[var(--muted)]">
                  no results — try lowering min_score
                </td>
              </tr>
            )}
            {results.map((r, i) => (
              <ScanRow key={r.ticker} r={r} index={i} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
