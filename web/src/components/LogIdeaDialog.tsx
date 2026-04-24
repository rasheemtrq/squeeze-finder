"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, X, Loader2 } from "lucide-react";
import { openIdea, type TickerResult } from "@/lib/api";

export function LogIdeaDialog({ ticker }: { ticker: TickerResult }) {
  const [open, setOpen] = useState(false);
  const [thesis, setThesis] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [timeStop, setTimeStop] = useState("");
  const [force, setForce] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const requiresForce = ticker.score < 70;

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await openIdea({
        ticker: ticker.ticker,
        thesis,
        invalidation,
        time_stop: timeStop || undefined,
        force: requiresForce ? force : false,
      });
      setOpen(false);
      router.push("/ideas");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-[var(--foreground)] text-[var(--background)] hover:bg-white/90 transition-colors font-medium"
      >
        <Plus className="w-3.5 h-3.5" />
        log idea
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => !submitting && setOpen(false)}
        >
          <div
            className="bg-[var(--surface)] ring-border rounded-lg max-w-md w-full p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">
                  log idea · <span className="mono">{ticker.ticker}</span>
                </div>
                <div className="text-xs text-[var(--muted)]">
                  composite score {ticker.score.toFixed(0)} ·{" "}
                  {requiresForce ? "below 70 threshold — force required" : "above threshold"}
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                disabled={submitting}
                className="text-[var(--muted)] hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <Field label="thesis *" hint="why this could squeeze — be specific">
                <textarea
                  value={thesis}
                  onChange={(e) => setThesis(e.target.value)}
                  rows={3}
                  className="w-full bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm outline-none focus:ring-white/40 resize-none"
                  placeholder="ST hot (150 msgs, 96% bull), gamma 0.45 near 5/9, FINRA short vol 53% and rising"
                />
              </Field>

              <Field label="invalidation *" hint="concrete level or condition that kills the thesis">
                <textarea
                  value={invalidation}
                  onChange={(e) => setInvalidation(e.target.value)}
                  rows={2}
                  className="w-full bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm outline-none focus:ring-white/40 resize-none"
                  placeholder="close < 22 OR gamma_conc drops < 0.35"
                />
              </Field>

              <Field label="time stop" hint="optional — YYYY-MM-DD">
                <input
                  type="date"
                  value={timeStop}
                  onChange={(e) => setTimeStop(e.target.value)}
                  className="w-full bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm outline-none focus:ring-white/40 mono"
                />
              </Field>

              {requiresForce && (
                <label className="flex items-start gap-2 text-xs text-[var(--muted)] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={force}
                    onChange={(e) => setForce(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Override score threshold — score is {ticker.score.toFixed(0)} (below 70).
                    Only do this with a specific reason beyond the composite.
                  </span>
                </label>
              )}

              {error && (
                <div className="text-xs text-[var(--danger-fg)] mono">{error}</div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-[var(--border)]">
              <button
                onClick={() => setOpen(false)}
                disabled={submitting}
                className="px-3 py-1.5 rounded-md text-sm text-[var(--muted)] hover:text-white transition-colors"
              >
                cancel
              </button>
              <button
                onClick={submit}
                disabled={
                  submitting ||
                  !thesis.trim() ||
                  !invalidation.trim() ||
                  (requiresForce && !force)
                }
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-[var(--foreground)] text-[var(--background)] font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                open idea
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
          {label}
        </label>
        {hint && <span className="text-[10px] text-[var(--muted)]">{hint}</span>}
      </div>
      {children}
    </div>
  );
}
