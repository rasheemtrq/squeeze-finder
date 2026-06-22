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
| Price / OHLCV | **Finnhub** (primary when key present) + yfinance fallback | `src/data/prices.py` + `src/data/finnhub.py` | ✅ | 60/min free (Finnhub) | 5min (quote), 1d (EOD) | 1m (quote) / 1d | `FINNHUB_API_KEY` strongly recommended |
| Fundamentals / float | **Finnhub** profile (primary) + yfinance + SEC EDGAR | `src/data/fundamentals.py` | ✅ | 60/min free | 7d | 1d | `FINNHUB_API_KEY` |
| Short interest % | FINRA short-sale files | `src/data/finra.py` (velocity) + yfinance | ✅ | Static files, no limit | until next report | 20d | none |
| Fails-to-Deliver (FTD) | SEC official CNS data (bulk monthly zips) | `src/data/ftd.py` + `ftd_downloader.py` | ✅ | Best free settlement-pressure signal | Ingest infrequently (manual or scheduled `ftd refresh`); query is local-only | 30–90d | none | Strongest free complement to RegSHO + FINRA short volume for the L factor in pressure score. Never fetch on hot scan path. |
| Options chain | yfinance | `src/data/options.py` | ✅ | 2 req/s | 15min | 1h | none |
| WSB mentions | Apewisdom aggregator | `src/data/apewisdom.py` | ✅ | Generous, public, no auth | 15min | 1h | none (scraper-free; uses pre-aggregated WSB top-100) |
| WSB mentions (alt) | Reddit PRAW | `src/data/reddit.py` | ✅ | 100 req/min with auth | 15min | 1h | DEFERRED — Apewisdom is sufficient for squeeze signal; PRAW gives deeper per-post access if needed later |
| StockTwits | public JSON endpoints | `src/data/stocktwits.py` | ✅ | ~200 req/hr, unofficial | 10min | 1h | none |
| Earnings calendar | Finnhub free | `src/data/catalysts.py` (primary) | ✅ | 60 req/min (very generous free tier) | 6h | 1d | `FINNHUB_API_KEY` |
| Quote / Prices | Finnhub | `src/data/finnhub.py` (NEW - strong recommendation) | ✅ | 60/min free | Use as primary or fast fallback to yfinance | 1m (quote) | `FINNHUB_API_KEY` |
| Company Profile / Fundamentals | Finnhub | `src/data/finnhub.py` | ✅ | 60/min free | Excellent shares outstanding, market cap, sector | 1d | `FINNHUB_API_KEY` |
| FDA events (PDUFA, advisory) | openFDA | `src/data/catalysts_fda.py` | ✅ | 240/min unauth, 120k/day | 1d | 7d | optional `OPENFDA_API_KEY` for higher |
| 8-K filings | SEC EDGAR | `src/data/filings.py` | ✅ | 10 req/s | 1h | 1d | User-Agent |
| Analyst narrative | OpenRouter | `src/analyst/openrouter.py` | free tier models | Varies per model | no cache | n/a | `OPENROUTER_API_KEY` |
| Fundamentals / News (lightweight supplement) | Alpha Vantage (prototype) | `src/data/alphavantage.py` | 25 calls/day free | Extremely limited | Use only post-scan on top N results | n/a | `ALPHAVANTAGE_API_KEY` (optional) |

## .env template
```
FINNHUB_API_KEY=          # Strongly recommended — 60 calls/min free tier. Excellent for quotes + fundamentals + catalysts
OPENROUTER_API_KEY=
SEC_USER_AGENT=squeeze-finder <your-email>

# deferred — add to enable Reddit sentiment
# REDDIT_CLIENT_ID=
# REDDIT_CLIENT_SECRET=
# REDDIT_USER_AGENT=squeeze-finder/0.1 by <your-username>

# optional / limited
# ALPHAVANTAGE_API_KEY=   # 25 calls/day free — only for post-scan enrichment on top results
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
| yfinance prices | Finnhub `/quote` (primary) | Much more reliable |
| yfinance fundamentals | Finnhub profile (primary) | Much more reliable |
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
