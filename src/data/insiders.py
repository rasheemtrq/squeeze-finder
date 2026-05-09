"""
SEC EDGAR Form 4 insider transactions — open-market purchases by directors,
officers, and 10% owners. Filtered to transaction code "P" (open-market
purchase) only and to filings flagged as not under a Rule 10b5-1 plan.

Why this exists: insider buying on a heavily-shorted name is a textbook
squeeze precondition. Insiders see the borrow + shareholder count — when
they're putting personal capital in alongside crowded shorts, that's the
asymmetry. Pre-planned 10b5-1 sales/purchases are scheduled and carry no
information; we exclude them.

Data flow:
  1. ticker -> CIK via the canonical company_tickers.json (cached 7 days)
  2. CIK -> recent submissions JSON (Form-4-typed filings, cached 24h)
  3. Per Form 4 -> XML doc parsed for non-derivative purchase transactions
  4. Aggregate: total $ bought (last 90d), distinct insiders, cluster flag

Free, official, rate-limited by EDGAR to ~10 rps; we cap concurrency at 3
per ticker for the per-filing XML fetches and rely on the 24h cache to
keep the steady-state load near zero.
"""
from __future__ import annotations

import concurrent.futures
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import SEC_USER_AGENT
from src.data import _cache
from src.data.prices import DataUnavailable

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accno_nd}/{doc}"

CACHE_TTL_TICKERS = 7 * 86400  # ticker -> CIK map: weekly is plenty
CACHE_TTL_INSIDERS = 86400  # 24h — Form 4 must be filed within 2 business days
LOOKBACK_DAYS_DEFAULT = 90
MAX_FORM4_PER_TICKER = 30  # cap per scan to bound EDGAR work


def _headers() -> dict[str, str]:
    return {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _http_get(url: str, timeout: int = 15) -> httpx.Response:
    r = httpx.get(url, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r


def _ticker_to_cik_map() -> dict[str, str]:
    cached = _cache.get("sec_tickers", "all", CACHE_TTL_TICKERS)
    if cached:
        return cached
    data = _http_get(COMPANY_TICKERS_URL).json()
    # Source format: {"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc"}, ...}
    out: dict[str, str] = {}
    for entry in data.values():
        try:
            out[str(entry["ticker"]).upper()] = f"{int(entry['cik_str']):010d}"
        except (KeyError, TypeError, ValueError):
            continue
    _cache.put("sec_tickers", "all", out)
    return out


def _lookup_cik(ticker: str) -> str | None:
    return _ticker_to_cik_map().get(ticker.upper())


def _recent_form4_filings(cik: str, lookback_days: int) -> list[dict]:
    """Return the recent Form 4 filings for a CIK, newest first."""
    data = _http_get(SUBMISSIONS_URL.format(cik=cik)).json()
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accnos = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []

    cutoff = date.today() - timedelta(days=lookback_days)
    cik_int = int(cik)
    out: list[dict] = []
    for form_type, filing_date, accno, doc in zip(forms, dates, accnos, docs, strict=False):
        if form_type != "4":
            continue
        try:
            d = date.fromisoformat(filing_date)
        except ValueError:
            continue
        if d < cutoff:
            break
        # primaryDocument is usually the XSLT-rendered HTML view
        # (xslF345X06/wk-form4_*.xml). Strip that prefix to point at the raw
        # underlying XML, which is what we actually parse.
        raw_doc = doc.split("/", 1)[1] if doc.startswith("xslF345X") else doc
        url = ARCHIVE_URL.format(
            cik_int=cik_int, accno_nd=accno.replace("-", ""), doc=raw_doc
        )
        out.append({"filing_date": filing_date, "url": url, "accno": accno})
    return out[:MAX_FORM4_PER_TICKER]


def _parse_form4_xml(xml_text: str) -> dict | None:
    """Extract open-market purchase transactions from a Form 4 XML doc.

    Returns None if the doc isn't a parseable Form 4. The Form 4 schema:
      ownershipDocument
        reportingOwner
          reportingOwnerRelationship: isDirector / isOfficer / isTenPercentOwner
        nonDerivativeTable
          nonDerivativeTransaction
            transactionCoding/transactionCode  ("P" = open-market purchase)
            transactionAmounts/transactionShares/value
            transactionAmounts/transactionPricePerShare/value
            transactionDate/value
        footnotes (free text — we scan for "10b5-1")
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    if "ownershipDocument" not in root.tag and root.tag != "ownershipDocument":
        return None

    rel = root.find("reportingOwner/reportingOwnerRelationship")
    is_director = rel is not None and (rel.findtext("isDirector") or "").strip() in ("1", "true")
    is_officer = rel is not None and (rel.findtext("isOfficer") or "").strip() in ("1", "true")
    is_tenpct = rel is not None and (rel.findtext("isTenPercentOwner") or "").strip() in ("1", "true")
    owner_name = (root.findtext("reportingOwner/reportingOwnerId/rptOwnerName") or "").strip()

    footnote_blob = " ".join((fn.text or "") for fn in root.iter("footnote")).lower()
    is_10b5_1 = "10b5-1" in footnote_blob

    # Collect both purchases (P) and open-market sales (S). Sells are needed
    # for the insider-dumping red flag: insiders cashing out into a squeeze
    # is a textbook end-of-move signal that Reddit recurringly highlighted.
    transactions: list[dict] = []
    for tx in root.iter("nonDerivativeTransaction"):
        code = (tx.findtext("transactionCoding/transactionCode") or "").strip()
        if code not in ("P", "S"):
            continue
        try:
            shares = float(tx.findtext("transactionAmounts/transactionShares/value") or 0)
            price = float(tx.findtext("transactionAmounts/transactionPricePerShare/value") or 0)
        except (TypeError, ValueError):
            continue
        if shares <= 0 or price <= 0:
            continue
        tx_date = tx.findtext("transactionDate/value") or ""
        transactions.append({
            "date": tx_date,
            "code": code,
            "shares": shares,
            "price": round(price, 4),
            "value": round(shares * price, 2),
        })

    if not transactions:
        return None

    return {
        "owner_name": owner_name,
        "is_director": is_director,
        "is_officer": is_officer,
        "is_tenpct": is_tenpct,
        "is_10b5_1": is_10b5_1,
        "transactions": transactions,
    }


def _fetch_one_form4(filing: dict) -> dict | None:
    try:
        text = _http_get(filing["url"], timeout=10).text
    except Exception:
        return None
    parsed = _parse_form4_xml(text)
    if not parsed:
        return None
    return {**parsed, "filing_date": filing["filing_date"], "accno": filing["accno"]}


def fetch(ticker: str, lookback_days: int = LOOKBACK_DAYS_DEFAULT, force_refresh: bool = False) -> dict:
    """Return aggregated insider open-market buying for `ticker`.

    Output keys: total_buy_value_usd, total_buy_shares, distinct_insiders,
    cluster_buying (3+ insiders within 14 days), purchases (newest first).
    Excludes 10b5-1 plans. Raises DataUnavailable if the ticker has no CIK
    or EDGAR is unreachable on a cold cache.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_{lookback_days}"
    if not force_refresh:
        cached = _cache.get("insiders", cache_key, CACHE_TTL_INSIDERS)
        if cached:
            return cached

    cik = _lookup_cik(ticker)
    if not cik:
        raise DataUnavailable(f"no SEC CIK for {ticker}")

    try:
        filings = _recent_form4_filings(cik, lookback_days)
    except Exception as e:
        raise DataUnavailable(f"EDGAR submissions fetch failed for {ticker}: {e}") from e

    parsed: list[dict] = []
    if filings:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for r in pool.map(_fetch_one_form4, filings):
                if r and not r["is_10b5_1"]:
                    parsed.append(r)

    purchases: list[dict] = []
    sales: list[dict] = []
    for filing in parsed:
        for tx in filing["transactions"]:
            entry = {
                "date": tx["date"],
                "owner": filing["owner_name"],
                "is_director": filing["is_director"],
                "is_officer": filing["is_officer"],
                "is_tenpct": filing["is_tenpct"],
                "shares": tx["shares"],
                "price": tx["price"],
                "value": tx["value"],
                "filing_date": filing["filing_date"],
            }
            if tx.get("code") == "P":
                purchases.append(entry)
            elif tx.get("code") == "S":
                sales.append(entry)
    purchases.sort(key=lambda p: p["date"], reverse=True)
    sales.sort(key=lambda p: p["date"], reverse=True)

    total_buy_value = round(sum(p["value"] for p in purchases), 2)
    total_buy_shares = round(sum(p["shares"] for p in purchases), 0)
    distinct_buyers = len({p["owner"] for p in purchases if p["owner"]})

    total_sell_value = round(sum(s["value"] for s in sales), 2)
    total_sell_shares = round(sum(s["shares"] for s in sales), 0)
    distinct_sellers = len({s["owner"] for s in sales if s["owner"]})

    # Cluster-buy signal: 3+ distinct insiders buying within any 14-day
    # window. Strong contrarian-bullish in conjunction with high SI.
    cluster_buying = _cluster_window(purchases, min_owners=3, days=14)
    # Cluster-sell signal: same logic on the sell side. Reddit-corpus
    # consensus: insiders dumping into a squeeze is a recurring end-of-move
    # pattern. Treated as a red flag downstream.
    cluster_selling = _cluster_window(sales, min_owners=3, days=14)

    result = {
        "ticker": ticker,
        "cik": cik,
        "as_of": datetime.now(UTC).isoformat(),
        "lookback_days": lookback_days,
        "total_buy_value_usd": total_buy_value,
        "total_buy_shares": total_buy_shares,
        "distinct_insiders": distinct_buyers,  # legacy alias for buyers
        "distinct_buyers": distinct_buyers,
        "cluster_buying": cluster_buying,
        "total_sell_value_usd": total_sell_value,
        "total_sell_shares": total_sell_shares,
        "distinct_sellers": distinct_sellers,
        "cluster_selling": cluster_selling,
        "filings_seen": len(filings),
        "purchases": purchases[:25],
        "sales": sales[:25],
    }
    _cache.put("insiders", cache_key, result)
    return result


def _cluster_window(events: list[dict], min_owners: int, days: int) -> bool:
    """True if `min_owners` distinct owners had events in any `days`-day window."""
    if len({e["owner"] for e in events if e.get("owner")}) < min_owners:
        return False
    by_owner: dict[str, list[date]] = {}
    for e in events:
        try:
            d = date.fromisoformat(e["date"])
        except ValueError:
            continue
        if e.get("owner"):
            by_owner.setdefault(e["owner"], []).append(d)
    all_dates = sorted({d for ds in by_owner.values() for d in ds})
    for anchor in all_dates:
        window_end = anchor + timedelta(days=days)
        owners_in_window = {
            o for o, ds in by_owner.items()
            if any(anchor <= d <= window_end for d in ds)
        }
        if len(owners_in_window) >= min_owners:
            return True
    return False
