# squeeze finder

Short-squeeze scanner + analyst for US equities. 5-factor composite (sentiment, options/gamma, short interest, technicals, catalysts). Free data only.

## Stack
- **Backend** — Python 3.11+, FastAPI, yfinance, curl_cffi, httpx
- **Frontend** — Next.js 16, React 19, Tailwind 4, Geist fonts
- **Data sources** — yfinance, StockTwits, Finnhub (earnings)
- **LLM narratives** — OpenRouter free models (planned, v2 UI)

## Quickstart

```bash
# 1. install backend deps (once)
uv pip install -e .

# 2. install frontend deps (once)
cd web && pnpm install && cd ..

# 3. copy env template and fill keys
cp .env.example .env
#   FINNHUB_API_KEY=...
#   OPENROUTER_API_KEY=...

# 4. run both servers
make dev
```

Open http://localhost:3000.

First scan hits ~47 tickers live and takes 30–60s. Subsequent scans hit disk cache.

## Individual commands

```bash
make api                          # FastAPI only on :8000
make web                          # Next.js only on :3000
.venv/bin/python -m src.cli scan-cmd
.venv/bin/python -m src.cli analyze GME
```

API docs: http://127.0.0.1:8000/docs

## Project map
```
.claude/                      # agent skills & ops rules
  CLAUDE.md                   # weights, layout, rules
  skills/                     # squeeze-thesis, ticker-deepdive, etc.
src/
  config.py                   # env, TTLs, weights, universe
  scanner.py                  # orchestrates fetch + score for N tickers
  api.py                      # FastAPI
  cli.py                      # typer CLI
  data/                       # per-source fetchers (all cached)
  score/                      # per-factor + composite
web/
  src/app/                    # Next 16 app router
    page.tsx                  # dashboard (scan table)
    t/[symbol]/page.tsx       # ticker deepdive
    ideas/page.tsx            # tracker (v2)
  src/components/             # ScoreBadge, Flag, ScanTable
  src/lib/api.ts              # API client + format helpers
data/                         # cache, ideas log, deepdives (gitignored)
```

## Weights (default)
| Factor | Weight |
|---|---|
| StockTwits sentiment | 25% |
| Options / gamma | 25% |
| Short interest % | 25% |
| Technicals (60d break + rvol + rsi) | 15% |
| Catalyst proximity | 10% |

Override per-request: `/api/scan?w_sentiment=0.3&w_options=0.3&...` (auto-normalized).

Reddit/WSB sentiment is deferred. To enable: add Reddit app keys to `.env`, build `src/data/reddit.py` against the PRAW contract in `.claude/skills/data-sources/SKILL.md`, then extend `score_sentiment` in `src/score/factors.py` and bump weight back to 30% (SI → 20%).

## Disclaimer
Not investment advice. Ideas not trades. Free data can be stale (FINRA short interest is bi-monthly; yfinance cache freshness is opaque).
