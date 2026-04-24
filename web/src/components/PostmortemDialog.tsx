"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { X, Loader2 } from "lucide-react";
import { submitPostmortem } from "@/lib/api";

const OUTCOMES = ["win", "loss", "flat"] as const;
const CALIBRATIONS = ["correct", "wrong", "wrong_direction", "n/a"];
const FACTORS = ["sentiment", "options", "si", "ta", "catalyst"] as const;

export function PostmortemDialog({
  ideaId,
  open,
  onClose,
}: {
  ideaId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]>("flat");
  const [returnPct, setReturnPct] = useState("");
  const [whatWorked, setWhatWorked] = useState("");
  const [whatMissed, setWhatMissed] = useState("");
  const [lesson, setLesson] = useState("");
  const [calibration, setCalibration] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await submitPostmortem(ideaId, {
        outcome,
        return_ref_pct: returnPct ? Number(returnPct) : undefined,
        what_worked: whatWorked,
        what_missed: whatMissed,
        factor_calibration: calibration,
        lesson,
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
        className="bg-[var(--surface)] ring-border rounded-lg max-w-xl w-full p-5 space-y-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">post-mortem</div>
            <div className="text-xs text-[var(--muted)]">
              required after close · feeds weight calibration
            </div>
          </div>
          <button onClick={onClose} disabled={submitting} className="text-[var(--muted)] hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">outcome</label>
            <div className="flex gap-1 mt-1.5">
              {OUTCOMES.map((o) => (
                <button
                  key={o}
                  onClick={() => setOutcome(o)}
                  className={`px-3 py-1 rounded mono text-xs border transition-colors ${
                    outcome === o
                      ? "bg-white/10 border-white/40 text-white"
                      : "border-[var(--border)] text-[var(--muted)] hover:text-white"
                  }`}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              return ref %
            </label>
            <input
              type="number"
              step="0.1"
              value={returnPct}
              onChange={(e) => setReturnPct(e.target.value)}
              className="w-full mt-1.5 bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm mono outline-none focus:ring-white/40"
              placeholder="e.g. 12.5 or -8.2"
            />
          </div>

          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              what worked *
            </label>
            <textarea
              value={whatWorked}
              onChange={(e) => setWhatWorked(e.target.value)}
              rows={2}
              className="w-full mt-1.5 bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm outline-none focus:ring-white/40 resize-none"
            />
          </div>

          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              what missed *
            </label>
            <textarea
              value={whatMissed}
              onChange={(e) => setWhatMissed(e.target.value)}
              rows={2}
              className="w-full mt-1.5 bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm outline-none focus:ring-white/40 resize-none"
            />
          </div>

          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              factor calibration
            </label>
            <div className="text-[10px] text-[var(--muted)] mb-2">
              was each factor right about this trade?
            </div>
            <div className="space-y-1.5">
              {FACTORS.map((f) => (
                <div key={f} className="flex items-center gap-2">
                  <span className="mono text-xs w-20 text-[var(--muted)]">{f}</span>
                  <div className="flex gap-1 flex-wrap">
                    {CALIBRATIONS.map((c) => (
                      <button
                        key={c}
                        onClick={() =>
                          setCalibration({ ...calibration, [f]: calibration[f] === c ? "" : c })
                        }
                        className={`px-2 py-0.5 rounded mono text-[10px] border transition-colors ${
                          calibration[f] === c
                            ? "bg-white/10 border-white/40 text-white"
                            : "border-[var(--border)] text-[var(--muted)] hover:text-white"
                        }`}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              one lesson *
            </label>
            <textarea
              value={lesson}
              onChange={(e) => setLesson(e.target.value)}
              rows={2}
              className="w-full mt-1.5 bg-[var(--background)] ring-border rounded px-2.5 py-1.5 text-sm outline-none focus:ring-white/40 resize-none"
              placeholder="one sentence. actionable."
            />
          </div>

          {error && <div className="text-xs text-[var(--danger-fg)] mono">{error}</div>}
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-[var(--border)] sticky bottom-0 bg-[var(--surface)]">
          <button
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded-md text-sm text-[var(--muted)] hover:text-white"
          >
            cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || !whatWorked.trim() || !whatMissed.trim() || !lesson.trim()}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-[var(--foreground)] text-[var(--background)] font-medium disabled:opacity-40"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            submit
          </button>
        </div>
      </div>
    </div>
  );
}
