import clsx from "clsx";
import { scoreColor } from "@/lib/api";

export function ScoreBadge({ score, size = "md" }: { score: number; size?: "sm" | "md" | "lg" }) {
  const sizeClass = {
    sm: "text-[11px] px-1.5 py-0.5 min-w-[32px]",
    md: "text-xs px-2 py-0.5 min-w-[38px]",
    lg: "text-sm px-2.5 py-1 min-w-[48px]",
  }[size];
  return (
    <span
      className={clsx(
        "mono inline-flex items-center justify-center rounded border tabular-nums font-medium",
        scoreColor(score),
        sizeClass,
      )}
    >
      {score.toFixed(0)}
    </span>
  );
}

export function FactorBar({ score }: { score: number }) {
  return (
    <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
      <div
        className={clsx("h-full transition-all", {
          "bg-[var(--success-fg)]": score >= 75,
          "bg-[var(--warning-fg)]": score >= 60 && score < 75,
          "bg-white/70": score >= 40 && score < 60,
          "bg-[var(--muted)]/50": score < 40,
        })}
        style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
      />
    </div>
  );
}
