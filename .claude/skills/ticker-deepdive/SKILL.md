---
name: ticker-deepdive
description: Structured analyst writeup for a single squeeze candidate. Load when the user asks to analyze, deep-dive, research, or write up a specific ticker. Offloads narrative prose to a configurable OpenRouter model chain (free JSON-capable models by default; set OPENROUTER_MODELS to override, 30-min cached) while Claude (this agent) handles the structured reasoning, data stitching, and invalidation logic.
---

# Ticker Deepdive — analyst writeup

## When this skill is active
User says: "deep dive on TICKER", "analyze TICKER", "write up TICKER", "what's the case for TICKER", "research TICKER".

## Division of labor (cost optimization)
| Step | Who | Why |
|---|---|---|
| 1. Pull all data via `src/data/*` fetchers | Claude (code) | Precision, error handling |
| 2. Compute scores per `squeeze-thesis` | Claude (code) | Deterministic |
| 3. Assemble structured facts block (JSON) | Claude | Tight reasoning |
| 4. Generate narrative prose from facts | **OpenRouter free model** | Tokens are free |
| 5. Review narrative for factual drift | Claude | Cheap models hallucinate — verify against facts block |
| 6. Format final writeup | Claude | Keeps output discipline |

**OpenRouter model chain — configurable, free by default:**
- Source of truth: `config.OPENROUTER_MODELS` (env `OPENROUTER_MODELS`, comma-separated, tried in order).
- Default free chain: `nvidia/nemotron-3-super-120b-a12b:free` → `openai/gpt-oss-20b:free` — both empirically confirmed to return valid JSON on the free tier; quality-first, diverse providers so one rate-limiting doesn't kill narratives. (nex-agi/nex-n2-pro:free was dropped — it 429s constantly. Avoid reasoning-only free models — they burn the token budget on reasoning and return null content.)
- To upgrade quality, set `OPENROUTER_MODELS=anthropic/claude-haiku-4.5` (paid, ~$0.004/call).

Free-tier caveats: lower quality than paid, daily request caps, and occasional latency/outages — the multi-model fallback chain absorbs most of this. Results cached 30 min in `_cache` to limit repeats and rate-limit pressure. Step 5 (verify narrative against the facts block) matters MORE with free models — they hallucinate more.

Client wrapper: `src/analyst/openrouter.py::generate_narrative`. Call signature:
```python
narrative = generate_narrative(facts_block(ticker_result))
# returns {tldr: str, bull: [str,...], bear: [str,...], model_used: str}
```
The wrapper enforces JSON-mode response and validates shape. If every model in the chain fails or returns invalid JSON, the call raises `OpenRouterError` and the endpoint returns 502 — we surface the failure rather than fabricate a narrative.

## Output template (exact structure)
```markdown
# {TICKER} — Squeeze Deepdive  ({score}/100, {date})

## TL;DR
{2–3 sentence thesis, narrative from OR model}

## Facts
| Metric | Value | As of |
|---|---|---|
| Price / market cap | ${px} / ${mcap}M | {ts} |
| Float | {float}M shares | {ts} |
| Short interest % float | {si_pct}% | {finra_date} |
| Days to cover | {dtc} | {finra_date} |
| 24h WSB mentions (z) | {mentions} ({z}σ) | {ts} |
| StockTwits bull ratio | {bull}% ({n} msgs) | {ts} |
| Call/put ratio | {cpr} | {ts} |
| Gamma concentration (near-ATM) | {gamma_conc}% | {ts} |
| 60d breakout | {yes/no} @ rvol {rvol}x | {ts} |
| Next catalyst | {event} in {days}d | {src} |

## Factor scores
sentiment {s} · options {o} · SI {si} · TA {ta} · catalyst {c}

## Bull case
{3–5 bullets, narrative from OR model, must reference facts above}

## Bear case / invalidation
{3–5 bullets — what would kill this thesis. Claude-authored, not offloaded.}

## Position framework (informational only)
- Entry trigger: {specific price/event}
- Stop / invalidation price: {price}
- Time stop: {date — next catalyst + 2d, or 30d max}
- Size note: single-factor bets ≤ half size

## Data freshness warnings
{any factor with data >staleness threshold from data-sources skill}
```

## Hard rules
- **Every number in prose must appear in the Facts table.** Verify before output.
- **Bear case is never skipped.** If Claude can't find one, the thesis is too weak to write up.
- **No price targets.** Ranges are fine ("prior resistance at $X"). Specific targets are fiction.
- **No timing language beyond scheduled events.** "Could squeeze soon" is banned; "earnings 2026-05-01" is fine.
- If data is stale beyond thresholds in `data-sources` skill, state it upfront and cap conviction.

## Persist
After writeup, offer: *"Log this as an open idea in the tracker? (y/n)"*. On yes, invoke `idea-tracker` skill protocol.

## Invocation
```bash
uv run python -m src.cli analyze TICKER
uv run python -m src.cli analyze TICKER --model gemini  # override OR model
uv run python -m src.cli analyze TICKER --no-or         # Claude-only, skip OR
```
