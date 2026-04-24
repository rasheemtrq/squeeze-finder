import Link from "next/link";
import { ArrowUpRight, CircleDot, CircleCheck, CircleSlash } from "lucide-react";
import { fetchIdeas, type Idea } from "@/lib/api";
import { ScoreBadge } from "./ScoreBadge";
import { Logo } from "./Logo";

function statusIcon(status: Idea["status"]) {
  if (status === "open") return <CircleDot className="w-3.5 h-3.5 text-[var(--accent)]" />;
  if (status === "closed") return <CircleSlash className="w-3.5 h-3.5 text-[var(--warning-fg)]" />;
  return <CircleCheck className="w-3.5 h-3.5 text-[var(--success-fg)]" />;
}

function outcomeColor(outcome?: string | null) {
  if (outcome === "win") return "text-[var(--success-fg)]";
  if (outcome === "loss") return "text-[var(--danger-fg)]";
  if (outcome === "flat") return "text-[var(--muted)]";
  return "text-[var(--muted)]";
}

export async function IdeasTable() {
  let data;
  try {
    data = await fetchIdeas();
  } catch (e) {
    return (
      <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
        <div className="text-[var(--danger-fg)] font-medium mb-1">failed to load ideas</div>
        <div className="text-[var(--muted)] mono text-xs">{(e as Error).message}</div>
      </div>
    );
  }

  const { ideas } = data;

  if (ideas.length === 0) {
    return (
      <div className="rounded-md ring-border bg-[var(--surface)] p-12 text-center">
        <div className="text-sm mb-1">no ideas logged yet</div>
        <div className="text-xs text-[var(--muted)]">
          open one from any ticker detail page (/t/<span className="mono">TICKER</span>)
        </div>
      </div>
    );
  }

  const openCount = ideas.filter((i) => i.status === "open").length;
  const closedCount = ideas.filter((i) => i.status === "closed").length;
  const pmCount = ideas.filter((i) => i.status === "postmortemed").length;

  return (
    <div>
      <div className="flex gap-6 px-1 mb-3 text-xs text-[var(--muted)] mono">
        <span>
          <span className="text-[var(--accent)]">{openCount}</span> open
        </span>
        <span>
          <span className="text-[var(--warning-fg)]">{closedCount}</span> awaiting postmortem
        </span>
        <span>
          <span className="text-[var(--success-fg)]">{pmCount}</span> postmortemed
        </span>
      </div>
      <div className="rounded-md ring-border overflow-hidden bg-[var(--surface)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--surface-2)]">
            <tr className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">
              <th className="text-left font-normal px-3 py-2.5">status</th>
              <th className="text-left font-normal px-3 py-2.5">ticker</th>
              <th className="text-right font-normal px-3 py-2.5">entry</th>
              <th className="text-right font-normal px-3 py-2.5">score@entry</th>
              <th className="text-left font-normal px-3 py-2.5">thesis</th>
              <th className="text-right font-normal px-3 py-2.5">outcome</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {ideas.map((i) => (
              <tr
                key={i.idea_id}
                className="border-b border-[var(--border)] last:border-b-0 hover:bg-white/[0.02] group"
              >
                <td className="px-3 py-3">
                  <div className="inline-flex items-center gap-1.5 text-[11px] mono">
                    {statusIcon(i.status)}
                    <span className="text-[var(--muted)]">{i.status}</span>
                  </div>
                </td>
                <td className="px-3 py-3">
                  <Link
                    href={`/ideas/${i.idea_id}`}
                    className="flex items-center gap-2.5 group-hover:text-[var(--accent)] transition-colors"
                  >
                    <Logo ticker={i.ticker} size={24} />
                    <div className="flex flex-col gap-0.5 min-w-0">
                      <span className="mono font-medium">{i.ticker}</span>
                      <span className="text-[10px] text-[var(--muted)] mono">{i.idea_id}</span>
                    </div>
                  </Link>
                </td>
                <td className="px-3 py-3 mono tabular-nums text-right text-[var(--muted)]">
                  ${i.entry_ref_price?.toFixed(2) ?? "–"}
                </td>
                <td className="px-3 py-3 text-right">
                  <ScoreBadge score={i.score_at_entry} size="sm" />
                </td>
                <td className="px-3 py-3 text-xs text-[var(--muted)] max-w-[400px] truncate">
                  {i.thesis}
                </td>
                <td
                  className={`px-3 py-3 mono text-xs text-right ${outcomeColor(
                    i.postmortem?.outcome,
                  )}`}
                >
                  {i.postmortem
                    ? `${i.postmortem.outcome} · ${i.postmortem.return_ref_pct != null ? `${i.postmortem.return_ref_pct >= 0 ? "+" : ""}${i.postmortem.return_ref_pct.toFixed(1)}%` : "–"}`
                    : i.closed
                      ? "awaiting pm"
                      : "–"}
                </td>
                <td className="px-3 py-3 text-right">
                  <Link href={`/ideas/${i.idea_id}`} className="inline-flex opacity-0 group-hover:opacity-100">
                    <ArrowUpRight className="w-4 h-4 text-[var(--muted)]" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
