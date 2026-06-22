import { BrainView } from "@/components/BrainView";

export default function Brain() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-medium tracking-tight mb-2">trading bot brain</h1>
          <p className="text-[var(--muted)] text-sm max-w-2xl">
            Knowledge graph of the bot&apos;s trades. Signals are nodes — sized by how many trades used
            them, colored by realized expectancy (green = positive R, red = negative). Edges link signals
            that fired together. The bot leans toward the green and away from the red as it learns.
          </p>
        </div>
        <a href="/" className="shrink-0 text-[10px] mono text-[var(--muted)] hover:text-white transition-colors">
          ← scan
        </a>
      </div>
      <BrainView />
    </div>
  );
}
