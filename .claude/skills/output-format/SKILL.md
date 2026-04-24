---
name: output-format
description: Output discipline for all squeeze-finder responses — tables over prose, ranked lists, no preambles, no trailing summaries, code blocks only when executing or quoting code. Always active in this project.
---

# Output Format — response discipline

## When this skill is active
Always. This is a project-wide style governor for squeeze-finder.

## Rules

### Structure
- **Tables beat prose** for any comparison, ranking, or multi-metric output.
- **Ranked lists** when order matters; bullets when it doesn't; numbered steps only for procedures.
- **One H2 per section.** No nested headers deeper than H3.

### Opening / closing
- ❌ No preambles. Never start with "Great question", "Let me help you", "I'll now...".
- ❌ No trailing summaries. Do not end with "In summary" or restate what was just shown.
- ✅ Lead with the answer or the result. Context after, if needed.

### Precision
- Numbers always have units and `as_of` timestamp when it's market data.
- Percentages: one decimal (`28.4%`), not two.
- Prices: two decimals for equities.
- Never round short interest, float, or OI silently.

### Claims
- Prefix every data claim with its source: `[FINRA]`, `[yf]`, `[WSB]`, `[ST]`, `[Finnhub]`, `[openFDA]`, `[EDGAR]`, `[OR:<model>]`.
- If a number is computed, tag it `[calc]` and make the formula inspectable.
- If data is stale past threshold, prefix line with `STALE:`.

### Uncertainty
- "Likely", "probably", "could" are banned for price direction. Use them only for process ("this query likely needs a retry").
- When a factor signal is weak, say "weak signal" or "no edge" — not "potentially interesting."

### Code blocks
- Code blocks only for: actual code, CLI invocations, JSON/YAML payloads, file paths in a file tree.
- No pseudocode in code blocks. Prose it or write real code.

### File references
- Use markdown link syntax per VSCode context rules: `[src/score/composite.py:42](src/score/composite.py#L42)`.

### Length
- Screen output: top 20 rows max unless user asks for more.
- Deepdive: follows `ticker-deepdive` template exactly — don't pad.
- Status updates during tool use: one sentence.
- End-of-turn: one or two sentences, what changed and what's next.

## Templates

### Screen result
```
Top {n} by composite score · data_as_of {ts} · weights {w}

rank | ticker | score | sent | opts | si | ta | cat | flags
-----+--------+-------+------+------+----+----+-----+------
  1  | XYZ    |  84   |  92  |  78  | 88 | 60 | 72  | gamma_setup, STALE:si
...
```

### Factor explanation (on request)
```
{TICKER} sentiment = 85
  [WSB]  mentions_24h=412  z=3.8σ   threshold 3.0σ → contrib +22
  [ST]   bull_ratio=0.71   n=1820  threshold 0.50 → contrib +10.5
  [calc] 50 + 15*3.8 + 50*(0.71-0.50) = 117.5 → clipped to 100, half-weighted = 85
```

### Error / stale
```
ERROR: [Finnhub] 429 rate-limit, retrying in 8s (attempt 2/3)
STALE: [FINRA] last report 2026-04-02 (21d old > 20d threshold) — SI factor capped at 50
```

## Anti-patterns (don't do)
- ❌ Long paragraphs explaining what a table already shows
- ❌ "I checked X and found Y" — just show Y
- ❌ Emoji (unless user asks)
- ❌ Trailing "Let me know if you want me to dig deeper" — user will ask if they want more
- ❌ Repeating the user's question back to them
