---
name: data-sources
description: Authoritative map of which fetcher to use for each data type, with rate limits, cache TTLs, staleness thresholds, and auth requirements. Load whenever fetching market, sentiment, options, or catalyst data, or when a fetcher errors and an alternate path is needed.
---

# Data Sources — fetcher map

## When this skill is active
Any data pull. Also load when: "refresh data", "why is X stale", "switch provider for Y", fetcher errors, rate-limit hits.

## Source table

| Data | Primary source | Module | Free? | Rate limit | Cache TTL | Stale threshold | Auth |
|---|---|---|---|---|---|---|---|
| Price / OHLCV | yfinance | `src/data/prices.py` | ✅ | Unofficial — throttle to 2 req/s | 5min (intraday), 1d (EOD) | 1d | none |
| Fundamentals / float | yfinance + SEC EDGAR | `src/data/fundamentals.py` | ✅ | EDGAR 10 req/s hard | 7d | 30d | User-Agent header required for EDGAR |
| Short interest % | FINRA short-sale files | `src/data/si.py` | ✅ | Static files, no limit | until next report | 20d (report is bi-monthly) | none |
| Options chain | yfinance | `src/data/options.py` | ✅ | 2 req/s | 15min | 1h | none |
| WSB mentions | Apewisdom aggregator | `src/data/apewisdom.py` | ✅ | Generous, public, no auth | 15min | 1h | none (scraper-free; uses pre-aggregated WSB top-100) |
| WSB mentions (alt) | Reddit PRAW | `src/data/reddit.py` | ✅ | 100 req/min with auth | 15min | 1h | DEFERRED — Apewisdom is sufficient for squeeze signal; PRAW gives deeper per-post access if needed later |
| StockTwits | public JSON endpoints | `src/data/stocktwits.py` | ✅ | ~200 req/hr, unofficial | 10min | 1h | none |
| Earnings calendar | Finnhub free | `src/data/catalysts_earnings.py` | ✅ | 60 req/min | 6h | 1d | `FINNHUB_API_KEY` |
| FDA events (PDUFA, advisory) | openFDA | `src/data/catalysts_fda.py` | ✅ | 240/min unauth, 120k/day | 1d | 7d | optional `OPENFDA_API_KEY` for higher |
| 8-K filings | SEC EDGAR | `src/data/filings.py` | ✅ | 10 req/s | 1h | 1d | User-Agent |
| Analyst narrative | OpenRouter | `src/analyst/openrouter.py` | free tier models | Varies per model | no cache | n/a | `OPENROUTER_API_KEY` |

## .env template
```
FINNHUB_API_KEY=
OPENROUTER_API_KEY=
SEC_USER_AGENT=squeeze-finder <your-email>

# deferred — add to enable Reddit sentiment
# REDDIT_CLIENT_ID=
# REDDIT_CLIENT_SECRET=
# REDDIT_USER_AGENT=squeeze-finder/0.1 by <your-username>

# optional
# OPENFDA_API_KEY=
```

## Fetcher contract (all modules follow this)
```python
def fetch(ticker: str, *, force_refresh: bool = False) -> dict | pl.DataFrame:
    """
    Returns typed result. Logs 'CACHE {source} {ticker}' or 'FETCH {source} {ticker}'.
    Raises DataUnavailable on hard failure — caller decides to skip ticker or abort.
    Never returns partial/imputed values silently.
    """
```

## Staleness handling
Every fetcher attaches `as_of` timestamp. Composite scorer checks:
- If any factor data > stale threshold above, emit `STALE:{source}` warning in output
- If SI data > 30 days old, cap SI factor score at 50 (half weight)
- If sentiment data > 4 hours old during market hours, refetch before using

## Failure fallbacks
| Primary fails | Fallback | Notes |
|---|---|---|
| yfinance prices | `stooq.com` CSV via `src/data/prices.py::_stooq_fallback` | EOD only |
| yfinance options | stockanalysis.com scrape (last resort, fragile) | Flag `LOW_CONFIDENCE` |
| Reddit PRAW auth fail | currently deferred — no fallback needed | Re-enable requires keys in `.env` |
| StockTwits down | cap sentiment factor at 50 and flag `SENTIMENT_UNAVAILABLE` (no Reddit fallback until re-enabled) | Composite still runs on remaining 4 factors |
| Finnhub over quota | yfinance `.calendar` (less reliable) | |
| OpenRouter free tier saturated | try next free model in priority list | Fall back to Claude-only narrative |

## Rate-limit etiquette
- All fetchers use `tenacity` for retry with jitter on 429/5xx
- Global token bucket in `src/data/_rl.py` — don't bypass it
- Batch ticker fetches with `asyncio.gather` but cap concurrency to `min(source_rps, 5)`

## When adding a new source
1. Create `src/data/<source>.py` following the fetcher contract
2. Add row to table above (edit this SKILL.md)
3. Add cache TTL and stale threshold
4. Add `.env` vars if auth required
5. Add fallback if primary source is fragile
