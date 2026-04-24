import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { fetchIdea } from "@/lib/api";
import { ScoreBadge } from "@/components/ScoreBadge";
import { Logo } from "@/components/Logo";
import { IdeaActions } from "./actions";

export default async function IdeaDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let idea;
  try {
    idea = await fetchIdea(id);
  } catch (e) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <Link href="/ideas" className="text-sm text-[var(--muted)] hover:text-white">
          ← ideas
        </Link>
        <div className="mt-6 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm">
          <div className="text-[var(--danger-fg)]">idea not found</div>
          <div className="text-[var(--muted)] mono text-xs mt-1">{(e as Error).message}</div>
        </div>
      </div>
    );
  }

  const statusColor = {
    open: "text-[var(--accent)]",
    closed: "text-[var(--warning-fg)]",
    postmortemed: "text-[var(--success-fg)]",
  }[idea.status];

  return (
    <div className="mx-auto max-w-3xl px-6 py-10 space-y-6">
      <Link
        href="/ideas"
        className="inline-flex items-center gap-1.5 text-sm text-[var(--muted)] hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        ideas
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <Logo ticker={idea.ticker} size={40} />
          <div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-3xl font-medium mono tracking-tight">{idea.ticker}</h1>
              <Link
                href={`/t/${idea.ticker}`}
                className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition-colors"
              >
                view live →
              </Link>
            </div>
            <div className="text-xs text-[var(--muted)] mono mt-1">{idea.idea_id}</div>
            <div className={`text-xs mono mt-1 ${statusColor}`}>{idea.status}</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)] mb-1">
            score @ entry
          </div>
          <ScoreBadge score={idea.score_at_entry} size="lg" />
        </div>
      </div>

      <IdeaActions idea={idea} />

      <Section title="thesis">
        <p className="text-sm leading-relaxed">{idea.thesis}</p>
      </Section>

      <Section title="invalidation">
        <p className="text-sm leading-relaxed font-mono text-[var(--warning-fg)]">
          {idea.invalidation}
        </p>
      </Section>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Object.entries(idea.factors_at_entry).map(([k, v]) => (
          <div key={k} className="rounded-md ring-border bg-[var(--surface)] p-3">
            <div className="text-[10px] mono uppercase text-[var(--muted)]">{k}</div>
            <div className="mt-1">
              <ScoreBadge score={v} size="sm" />
            </div>
          </div>
        ))}
      </div>

      <Section title="metadata">
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs mono">
          <KV k="opened" v={new Date(idea.opened_at).toLocaleString()} />
          <KV k="entry ref" v={idea.entry_ref_price ? `$${idea.entry_ref_price.toFixed(2)}` : "–"} />
          <KV k="time stop" v={idea.time_stop ?? "–"} />
          {idea.notes && <KV k="notes" v={idea.notes} />}
        </div>
      </Section>

      {idea.closed && (
        <Section title="close">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs mono">
            <KV k="closed at" v={new Date(idea.closed.ts).toLocaleString()} />
            <KV k="reason" v={idea.closed.close_reason} />
            <KV
              k="exit ref"
              v={idea.closed.exit_ref_price ? `$${idea.closed.exit_ref_price.toFixed(2)}` : "–"}
            />
            <KV k="days held" v={String(idea.closed.days_held)} />
          </div>
        </Section>
      )}

      {idea.postmortem && (
        <Section title="post-mortem">
          <div className="space-y-3 text-sm">
            <div className="flex gap-4 mono text-xs">
              <span>
                outcome:{" "}
                <span
                  className={
                    idea.postmortem.outcome === "win"
                      ? "text-[var(--success-fg)]"
                      : idea.postmortem.outcome === "loss"
                        ? "text-[var(--danger-fg)]"
                        : "text-[var(--muted)]"
                  }
                >
                  {idea.postmortem.outcome}
                </span>
              </span>
              <span>
                return ref:{" "}
                <span className="text-white">
                  {idea.postmortem.return_ref_pct != null
                    ? `${idea.postmortem.return_ref_pct >= 0 ? "+" : ""}${idea.postmortem.return_ref_pct.toFixed(1)}%`
                    : "–"}
                </span>
              </span>
            </div>
            <div>
              <div className="text-[10px] mono uppercase text-[var(--muted)] mb-1">what worked</div>
              <div className="text-sm">{idea.postmortem.what_worked}</div>
            </div>
            <div>
              <div className="text-[10px] mono uppercase text-[var(--muted)] mb-1">what missed</div>
              <div className="text-sm">{idea.postmortem.what_missed}</div>
            </div>
            <div>
              <div className="text-[10px] mono uppercase text-[var(--muted)] mb-1">
                factor calibration
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs mono">
                {Object.entries(idea.postmortem.factor_calibration).map(([k, v]) => (
                  <KV key={k} k={k} v={String(v)} />
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] mono uppercase text-[var(--muted)] mb-1">lesson</div>
              <div className="text-sm italic">{idea.postmortem.lesson}</div>
            </div>
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md ring-border bg-[var(--surface)] p-4 space-y-2">
      <div className="text-[10px] mono uppercase tracking-wider text-[var(--muted)]">{title}</div>
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-[var(--muted)]">{k}</span>
      <span className="text-right">{v}</span>
    </div>
  );
}
