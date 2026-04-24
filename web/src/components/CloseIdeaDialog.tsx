"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { X, Loader2 } from "lucide-react";
import { closeIdea } from "@/lib/api";

const REASONS = ["target_hit", "invalidation_hit", "time_stop", "thesis_broken", "manual"];

export function CloseIdeaDialog({ ideaId, open, onClose }: {
  ideaId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("manual");
  const [exitPrice, setExitPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await closeIdea(ideaId, {
        close_reason: reason,
        exit_ref_price: exitPrice ? Number(exitPrice) : undefined,
      });
      onClose();
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={() => !submitting && onClose()}
    >
      <div
        className="bg-[var(--surface)] ring-border rounded-lg max-w-md w-full p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium">close idea</div>
          <button onClick={onClose} disabled={submitting} className="text-[var(--muted)] hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">reason</label>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {REASONS.map((r) => (
                <button
                  key={r}
                  onClick={() => setReason(r)}
                  className={`px-2 py-1 rounded mono text-[11px] border transition-colors ${
                    reason === r
                      ? "bg-white/10 border-white/40 text-white"
                      : "border-[var(--border)] text-[var(--muted)] hover:text-white"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              exit ref price
            </label>
            <input
              type="number"
              step="0.01"
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              className="w-full mt-1.5 bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm mono outline-none focus:ring-white/40"
              placeholder="0.00"
            />
          </div>

          <div className="text-[11px] text-[var(--muted)] pt-1">
            post-mortem is mandatory after close. you&apos;ll be prompted next.
          </div>

          {error && <div className="text-xs text-[var(--danger-fg)] mono">{error}</div>}
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-[var(--border)]">
          <button
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded-md text-sm text-[var(--muted)] hover:text-white"
          >
            cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-[var(--foreground)] text-[var(--background)] font-medium disabled:opacity-40"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            close
          </button>
        </div>
      </div>
    </div>
  );
}
