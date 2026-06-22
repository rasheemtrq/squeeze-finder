# squeeze-finder — agent operating rules

## Mission
Find US equities with 2–10x short-squeeze potential, deep-dive the best candidates, track ideas end-to-end. Free data sources only. Python stack.

## Non-negotiables
- **Never fabricate market data.** If a data call fails, say so and stop — do not infer SI %, float, or options values from "typical" values.
- **No trade execution.** This agent outputs ideas and analysis. Order entry is out of scope.
- **Free APIs only** unless the user explicitly adds a paid key. Current free sources: FINRA (SI, bi-monthly), yfinance (price/options/fundamentals), Reddit PRAW, StockTwits public, Finnhub free tier (earnings), openFDA (drug catalysts), SEC EDGAR.
- **Free OpenRouter models for narrative; Claude (this agent) for reasoning + code.** Long-form analyst writeups route through OpenRouter using the model chain in `config.OPENROUTER_MODELS` (default: `nex-agi/nex-n2-pro:free` as the sole model, user-chosen; it 429s often on the free tier and calls error during those windows). Override with the `OPENROUTER_MODELS` env var (e.g. set to `anthropic/claude-haiku-4.5` to go back to the paid model). Still needs a free `OPENROUTER_API_KEY`. Fail loudly if routing breaks — never fabricate a narrative. See `ticker-deepdive` skill.

## Ranking thesis (default weights)
| Factor | Weight | Source |
|---|---|---|
| Social sentiment spike | 30% | StockTwits + Apewisdom WSB |
| Unusual options / gamma setup | 25% | yfinance options chain |
| Short interest % float (>20% = max) | 20% | FINRA + yfinance fundamentals |
| Technical breakout confirmation | 15% | yfinance OHLCV + internal TA |
| Catalyst proximity (≤30 days) | 10% | Finnhub + openFDA |

Full scoring logic lives in `skills/squeeze-thesis/SKILL.md`. Weights are overridable per-run.

**Best setups**: `scan --sort-by pressure` (or API `sort_by=pressure`) ranks by the multiplicative pressure score (L·G·S). Use this when hunting imminent squeezes where all three pressures (lending, gamma, social) must fire. Composite remains the default for broad watchlists.

## Project layout (target)
```
squeeze-finder/
  .claude/            # skills + this file
  src/
    data/             # fetchers per source (si.py, reddit.py, stocktwits.py, options.py, ta.py, catalysts.py)
    score/            # per-factor scoring + composite ranker
    analyst/          # OpenRouter client + deepdive runner
    tracker/          # idea log (JSONL), open/close/post-mortem
    cli.py            # entry points: scan, analyze, track
  data/
    cache/            # API response cache (parquet/json, TTL per source)
    ideas.jsonl       # tracker log
    screens/          # historical screen snapshots
  tests/
  pyproject.toml
```

## Skills index
- `squeeze-thesis` — ranking formula & interpretation
- `ticker-deepdive` — analyst writeup template (offloads to OpenRouter)
- `data-sources` — which fetcher for which data, rate limits, staleness
- `idea-tracker` — logging & post-mortem protocol
- `output-format` — terse output rules (always-on)

## Conventions
- Python 3.11+, `uv` for env, `ruff` for lint/format, `pytest`.
- Dataframes: `polars` preferred, `pandas` only where lib forces it.
- All fetchers return typed dicts or `pl.DataFrame`, never print.
- All scripts idempotent and re-runnable; cache hits log `CACHE`, misses log `FETCH`.
