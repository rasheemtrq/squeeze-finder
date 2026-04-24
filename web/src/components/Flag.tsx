import clsx from "clsx";

const FLAG_STYLES: Record<string, string> = {
  "options:gamma_setup": "border-[var(--success)]/50 text-[var(--success-fg)] bg-[var(--success)]/10",
  "options:call_heavy": "border-[var(--warning)]/50 text-[var(--warning-fg)] bg-[var(--warning)]/10",
  "options:thin_options": "border-[var(--border-strong)] text-[var(--muted)]",
  "si:squeeze_setup": "border-[var(--success)]/50 text-[var(--success-fg)] bg-[var(--success)]/10",
  "si:extreme_si": "border-[var(--success)]/50 text-[var(--success-fg)] bg-[var(--success)]/10",
  "sentiment:hot": "border-[var(--warning)]/50 text-[var(--warning-fg)] bg-[var(--warning)]/10",
  "sentiment:bearish_crowd": "border-[var(--danger)]/50 text-[var(--danger-fg)] bg-[var(--danger)]/10",
  "ta:breakout_highvol": "border-[var(--success)]/50 text-[var(--success-fg)] bg-[var(--success)]/10",
  "ta:breakout_lowvol": "border-[var(--warning)]/50 text-[var(--warning-fg)] bg-[var(--warning)]/10",
  "ta:overextended": "border-[var(--danger)]/50 text-[var(--danger-fg)] bg-[var(--danger)]/10",
  "ta:volume_spike": "border-[var(--warning)]/50 text-[var(--warning-fg)] bg-[var(--warning)]/10",
  "catalyst:imminent": "border-[var(--success)]/50 text-[var(--success-fg)] bg-[var(--success)]/10",
  "catalyst:near": "border-[var(--warning)]/50 text-[var(--warning-fg)] bg-[var(--warning)]/10",
  "risk:illiquid": "border-[var(--danger)]/50 text-[var(--danger-fg)] bg-[var(--danger)]/10",
  "risk:late_party": "border-[var(--danger)]/50 text-[var(--danger-fg)] bg-[var(--danger)]/10",
};

export function Flag({ flag }: { flag: string }) {
  const normalized = flag.includes("STALE") ? flag : flag;
  const base = FLAG_STYLES[normalized] || "border-[var(--border-strong)] text-[var(--muted)]";
  const stale = flag.includes("STALE");
  return (
    <span
      className={clsx(
        "mono inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] tabular-nums",
        base,
        stale && "italic",
      )}
    >
      {flag}
    </span>
  );
}
