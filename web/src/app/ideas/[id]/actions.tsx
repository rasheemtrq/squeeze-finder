"use client";

import { useState } from "react";
import { XCircle, FileText } from "lucide-react";
import { type Idea } from "@/lib/api";
import { CloseIdeaDialog } from "@/components/CloseIdeaDialog";
import { PostmortemDialog } from "@/components/PostmortemDialog";

export function IdeaActions({ idea }: { idea: Idea }) {
  const [closeOpen, setCloseOpen] = useState(false);
  const [pmOpen, setPmOpen] = useState(false);

  if (idea.status === "postmortemed") {
    return (
      <div className="text-xs text-[var(--muted)] mono">
        idea is complete — append-only log, no further actions.
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      {idea.status === "open" && (
        <button
          onClick={() => setCloseOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-[var(--border-strong)] hover:border-white/40 transition-colors"
        >
          <XCircle className="w-3.5 h-3.5" />
          close idea
        </button>
      )}
      {idea.status === "closed" && !idea.postmortem && (
        <button
          onClick={() => setPmOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-[var(--warning)]/20 border border-[var(--warning)]/50 text-[var(--warning-fg)] hover:bg-[var(--warning)]/30 transition-colors"
        >
          <FileText className="w-3.5 h-3.5" />
          write post-mortem (required)
        </button>
      )}
      <CloseIdeaDialog ideaId={idea.idea_id} open={closeOpen} onClose={() => setCloseOpen(false)} />
      <PostmortemDialog ideaId={idea.idea_id} open={pmOpen} onClose={() => setPmOpen(false)} />
    </div>
  );
}
