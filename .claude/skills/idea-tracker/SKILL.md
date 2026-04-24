---
name: idea-tracker
description: Protocol for logging, updating, closing, and post-morteming squeeze ideas. Load when the user says log/track/open/close/review an idea or position, wants to see open ideas, or asks for a post-mortem or weekly review.
---

# Idea Tracker — logging & review protocol

## When this skill is active
User says: "log this idea", "track TICKER", "close TICKER", "review open ideas", "post-mortem", "weekly review", "how's my hit rate".

## Storage
- File: `data/ideas.jsonl` (append-only, one JSON object per line)
- Screen snapshots: `data/screens/YYYY-MM-DD.jsonl` (for historical what-if backtesting)
- Never edit existing lines. State changes are new events with `event` field.

## Event schema
```json
{
  "event": "open | update | close | postmortem",
  "ts": "2026-04-23T14:05:00-04:00",
  "ticker": "GME",
  "idea_id": "2026-04-23-GME-01",
  "score_at_entry": 82,
  "factors": {"sentiment": 85, "options": 78, "si": 90, "ta": 60, "catalyst": 40},
  "thesis": "WSB mention z=4.2, gamma conc 0.52 near 4/26 expiry, SI 28% float",
  "invalidation": "close below 21-EMA or gamma conc drops <0.35",
  "time_stop": "2026-05-10",
  "entry_ref_price": 24.80,
  "sources_as_of": {"si": "2026-04-15", "sentiment": "2026-04-23T13:55", "options": "..."},
  "deepdive_ref": "data/deepdives/2026-04-23-GME.md",
  "notes": ""
}
```

### `open` (new idea)
Required: all fields above except `close` / `postmortem` specifics.

### `update`
Minimal: `{event, ts, ticker, idea_id, notes, factors?, invalidation?}`. Use for material updates only (score shift >10, new catalyst, thesis change). Do not spam updates.

### `close`
Required: `{event, ts, ticker, idea_id, exit_ref_price, close_reason, days_held, peak_drawup_pct, peak_drawdown_pct}`.
`close_reason` enum: `target_hit | invalidation_hit | time_stop | thesis_broken | manual`.

### `postmortem`
Required after every `close`. Required fields:
```json
{
  "event": "postmortem",
  "ts": "...",
  "ticker": "...",
  "idea_id": "...",
  "outcome": "win | loss | flat",
  "return_ref_pct": 37.2,
  "what_worked": "gamma call was correct, squeeze triggered off 4/25 OI",
  "what_missed": "underweighted TA — chart was already extended at entry",
  "factor_calibration": {"sentiment": "correct", "options": "correct", "si": "correct", "ta": "wrong_direction", "catalyst": "n/a"},
  "lesson": "cap entries when RSI14 >75 even if composite score is high"
}
```
Lessons feed back into weight-tuning. Review `postmortem.lesson` fields before re-tuning weights.

## Protocols

### Opening an idea
1. Must be preceded by a `ticker-deepdive` writeup saved to `data/deepdives/`
2. Score at entry must be ≥70 OR user explicitly overrides with `--force` and provides a reason (stored in `notes`)
3. `invalidation` field must be concrete (price level, factor threshold, or dated event). Reject vague "if thesis breaks."
4. Generate `idea_id` as `YYYY-MM-DD-TICKER-NN` (NN = sequence that day)

### Updating
- Only emit on material change. Rule of thumb: would a reader learn something?
- If composite score drops ≥20 points from entry without an invalidation trigger, prompt user: *"Score collapsed from {X} → {Y}. Close or downgrade?"*

### Closing
1. Prompt for `close_reason` if not provided
2. Compute `days_held`, `return_ref_pct` from entry/exit ref prices (label as reference, not realized P&L — this agent doesn't know actual fills)
3. **Immediately** require `postmortem` event before returning control — no open loops

### Weekly review (user says "weekly review")
Produce:
1. Open ideas table: ticker, age, score_at_entry, current_score (recompute), drift, status
2. Closed this week: ticker, outcome, return_ref_pct, lesson
3. Hit rate: wins / (wins + losses) over trailing 30d, 90d, all-time
4. Factor calibration: per factor, % of closed ideas where that factor was "correct" — flags which factor weights to tune
5. **One concrete tuning recommendation** based on calibration (e.g., "sentiment correct 78% but TA correct 42% — consider lowering TA weight from 15 → 10")

## Hard rules
- Never overwrite `data/ideas.jsonl` — append only
- Never invent historical prices for post-mortem returns — pull from data source, mark as ref
- Post-mortem is mandatory on close. No exceptions.
- Do not compute P&L in dollars — this agent doesn't know position size

## Invocation
```bash
uv run python -m src.cli idea open TICKER
uv run python -m src.cli idea close TICKER --reason target_hit
uv run python -m src.cli idea list
uv run python -m src.cli review weekly
```
