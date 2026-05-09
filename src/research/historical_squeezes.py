"""
Historical-squeeze backtest harness.

Replays our scoring on the days BEFORE confirmed historical squeezes and
reports how the algorithm would have ranked each name. Used to answer the
honest empirical question: "which of our factors actually fire on real
squeezes vs which are theoretically clean but historically silent?"

DATA-AVAILABILITY CAVEAT (read this before interpreting output):
  Historically-available factors  -> TA (prices), FINRA daily short ratios,
                                     insider Form 4 (SEC EDGAR), regime
                                     (SPY/VIX).
  Historically-UNAVAILABLE factors -> StockTwits/WSB sentiment (no archive),
                                     yfinance-snapshot SI% (current-only),
                                     options chain IV/gamma/CPR (current-only).

So this is a *partial-composite* replay. The output reports which factors
were available + their scores per case, plus an aggregate table of which
flags fired most reliably. Names that scored high on the partial composite
T-N days before a known squeeze are evidence those factors contain real
predictive signal; names that didn't, point at where we need to invest.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import SEC_USER_AGENT
from src.score.factors import (
    score_si as live_score_si,
)
from src.score.factors import (
    score_ta as live_score_ta,
)

# ---------------------------------------------------------------- cases ----

SqueezeCase = dict[str, Any]

# Curated list of well-documented short-squeezes / explosive moves driven
# largely by short positioning. Dates are the *day of peak*. Returns are
# rough peak-relative-to-30d-prior magnitudes from public price history.
# Cases are deliberately heterogeneous (mega-meme to micro-cap to biotech
# blow-off) so we don't tune the algorithm to one regime.
SQUEEZE_CASES: list[SqueezeCase] = [
    # 2021 meme wave
    {"ticker": "GME",  "squeeze_date": "2021-01-27", "peak_return_pct": 1700, "notes": "WSB-driven mega-squeeze, 140%+ SI"},
    {"ticker": "AMC",  "squeeze_date": "2021-06-02", "peak_return_pct": 500,  "notes": "second leg of meme wave, gamma chase"},
    {"ticker": "KOSS", "squeeze_date": "2021-01-27", "peak_return_pct": 2000, "notes": "small-float meme, rode GME momentum"},
    {"ticker": "EXPR", "squeeze_date": "2021-01-27", "peak_return_pct": 600,  "notes": "small-float retailer, WSB"},
    {"ticker": "BBBY", "squeeze_date": "2022-08-17", "peak_return_pct": 400,  "notes": "Cohen letter + retail, dilution killer"},
    {"ticker": "ATER", "squeeze_date": "2021-09-13", "peak_return_pct": 200,  "notes": "small-cap, ortex-flagged"},
    {"ticker": "BBIG", "squeeze_date": "2021-09-21", "peak_return_pct": 250,  "notes": "spinoff catalyst + high SI"},
    {"ticker": "IRNT", "squeeze_date": "2021-09-28", "peak_return_pct": 600,  "notes": "post-SPAC squeeze, tiny float"},
    {"ticker": "SPRT", "squeeze_date": "2021-08-27", "peak_return_pct": 1000, "notes": "post-SPAC merger, sub-1M float"},
    {"ticker": "RDBX", "squeeze_date": "2022-06-03", "peak_return_pct": 500,  "notes": "Redbox merger arb + WSB attention"},
    {"ticker": "MMAT", "squeeze_date": "2021-06-25", "peak_return_pct": 250,  "notes": "post-merger meme"},
    {"ticker": "HKD",  "squeeze_date": "2022-07-29", "peak_return_pct": 5000, "notes": "post-IPO sub-100k float"},
]


# ------------------------------------------------------ histo data fetch ---


def _hist_bars(ticker: str, end: date, lookback_days: int = 90) -> list[dict] | None:
    """OHLCV bars ending on or before `end`. Returns None on failure."""
    start = end - timedelta(days=int(lookback_days * 1.6))  # buffer for weekends
    try:
        h = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
    except Exception:
        return None
    if h.empty:
        return None
    h = h.reset_index()
    bars = []
    for _, row in h.iterrows():
        d = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
        bars.append({
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })
    return bars


# FINRA daily short volume — historical CSVs are publicly archived
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def _finra_day(d: date) -> str | None:
    s = d.strftime("%Y%m%d")
    r = httpx.get(FINRA_URL.format(date=s), timeout=20)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def _hist_finra(ticker: str, end: date, lookback_days: int = 7) -> dict | None:
    """Reproduces score-time FINRA structure but anchored at `end` instead of today."""
    series: list[dict] = []
    needle = f"|{ticker.upper()}|"
    d = end
    tries = 0
    while tries < lookback_days * 2 and len(series) < lookback_days:
        tries += 1
        try:
            text = _finra_day(d)
        except Exception:
            text = None
        d = d - timedelta(days=1)
        if not text:
            continue
        for line in text.splitlines():
            if needle not in line:
                continue
            parts = line.split("|")
            if len(parts) < 5:
                break
            try:
                short_v = float(parts[2])
                total_v = float(parts[4])
                if total_v <= 0:
                    break
                series.append({
                    "date": parts[0],
                    "short_ratio": round(short_v / total_v, 4),
                })
            except ValueError:
                pass
            break

    if not series:
        return None

    ratios = [r["short_ratio"] for r in series]
    avg_ratio = sum(ratios) / len(ratios)
    latest_ratio = ratios[0]
    trend = "flat"
    if len(ratios) >= 3:
        recent3 = sum(ratios[:3]) / 3
        prior = sum(ratios[3:]) / max(1, len(ratios) - 3)
        if prior > 0:
            delta = (recent3 - prior) / prior
            trend = "rising" if delta > 0.10 else "falling" if delta < -0.10 else "flat"

    return {
        "latest_short_ratio": latest_ratio,
        "avg_short_ratio": round(avg_ratio, 4),
        "trend": trend,
        "latest_date": series[0]["date"],
    }


# SEC EDGAR Form 4 — historical archive is complete (filings are immutable)


def _ticker_to_cik() -> dict[str, str]:
    r = httpx.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": SEC_USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    return {
        str(e["ticker"]).upper(): f"{int(e['cik_str']):010d}"
        for e in r.json().values()
    }


def _hist_insider_purchases(ticker: str, end: date, lookback_days: int = 90) -> dict:
    """Aggregate insider open-market purchases in [end - lookback_days, end].

    Walks SEC's submissions JSON for the CIK, filters Form 4 filings in
    the window, fetches each XML, sums `transactionCode == "P"` non-10b5-1
    purchases. Mirrors the live insiders fetcher logic but anchored at a
    historical `end` date.
    """
    try:
        cik_map = _ticker_to_cik()
    except Exception:
        return {"total_buy_value_usd": 0, "distinct_insiders": 0, "cluster_buying": False}
    cik = cik_map.get(ticker.upper())
    if not cik:
        return {"total_buy_value_usd": 0, "distinct_insiders": 0, "cluster_buying": False}

    cutoff_lo = end - timedelta(days=lookback_days)
    headers = {"User-Agent": SEC_USER_AGENT}

    try:
        sub = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=headers,
            timeout=20,
        ).json()
    except Exception:
        return {"total_buy_value_usd": 0, "distinct_insiders": 0, "cluster_buying": False}

    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accnos = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []

    targets: list[tuple[str, str]] = []
    for form_type, fd, accno, doc in zip(forms, dates, accnos, docs, strict=False):
        if form_type != "4":
            continue
        try:
            d = date.fromisoformat(fd)
        except ValueError:
            continue
        if d > end or d < cutoff_lo:
            continue
        raw_doc = doc.split("/", 1)[1] if doc.startswith("xslF345X") else doc
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accno.replace('-', '')}/{raw_doc}"
        )
        targets.append((fd, url))

    purchases: list[dict] = []
    for fd, url in targets[:30]:  # cap
        try:
            xml_text = httpx.get(url, headers=headers, timeout=10).text
            root = ET.fromstring(xml_text)
        except Exception:
            continue
        if "ownershipDocument" not in root.tag:
            continue
        owner = (root.findtext("reportingOwner/reportingOwnerId/rptOwnerName") or "").strip()
        footnote_blob = " ".join((fn.text or "") for fn in root.iter("footnote")).lower()
        if "10b5-1" in footnote_blob:
            continue
        for tx in root.iter("nonDerivativeTransaction"):
            code = (tx.findtext("transactionCoding/transactionCode") or "").strip()
            if code != "P":
                continue
            try:
                shares = float(tx.findtext("transactionAmounts/transactionShares/value") or 0)
                price = float(tx.findtext("transactionAmounts/transactionPricePerShare/value") or 0)
            except (TypeError, ValueError):
                continue
            if shares <= 0 or price <= 0:
                continue
            purchases.append({
                "owner": owner,
                "value": shares * price,
                "date": tx.findtext("transactionDate/value") or fd,
            })

    distinct = len({p["owner"] for p in purchases if p["owner"]})
    cluster = False
    if distinct >= 3:
        # 3+ distinct insiders within any 14-day window
        by_owner: dict[str, list[date]] = {}
        for p in purchases:
            try:
                d = date.fromisoformat(p["date"])
            except ValueError:
                continue
            by_owner.setdefault(p["owner"], []).append(d)
        all_dates = sorted({d for ds in by_owner.values() for d in ds})
        for anchor in all_dates:
            wend = anchor + timedelta(days=14)
            owners = {
                o for o, ds in by_owner.items()
                if any(anchor <= d <= wend for d in ds)
            }
            if len(owners) >= 3:
                cluster = True
                break

    return {
        "total_buy_value_usd": round(sum(p["value"] for p in purchases), 2),
        "distinct_insiders": distinct,
        "cluster_buying": cluster,
    }


def _hist_regime(end: date) -> dict:
    """SPY 50d EMA + VIX as-of `end`. Returns the same shape as src.data.regime."""
    try:
        spy = yf.Ticker("SPY").history(
            start=(end - timedelta(days=120)).isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
        vix = yf.Ticker("^VIX").history(
            start=(end - timedelta(days=10)).isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
    except Exception:
        return {"regime": "unknown", "multiplier": 1.0}
    if spy.empty or vix.empty or len(spy) < 50:
        return {"regime": "unknown", "multiplier": 1.0}
    spy_close = float(spy["Close"].iloc[-1])
    # 50-period EMA on Close
    k = 2 / (50 + 1)
    e = float(spy["Close"].iloc[0])
    for v in spy["Close"].iloc[1:]:
        e = float(v) * k + e * (1 - k)
    spy_above = spy_close > e
    vix_close = float(vix["Close"].iloc[-1])
    if not spy_above or vix_close > 25:
        return {"regime": "risk_off", "multiplier": 0.70, "vix": vix_close, "spy_above_ema": spy_above}
    if spy_above and vix_close < 14:
        return {"regime": "frothy", "multiplier": 1.05, "vix": vix_close, "spy_above_ema": True}
    return {"regime": "risk_on", "multiplier": 1.00, "vix": vix_close, "spy_above_ema": True}


# --------------------------------------------------- partial composite ----


def evaluate_case_at(case: SqueezeCase, t_minus: int) -> dict[str, Any]:
    """Evaluate a single case at T-`t_minus` days before its squeeze date."""
    sd = date.fromisoformat(case["squeeze_date"])
    asof = sd - timedelta(days=t_minus)

    bars = _hist_bars(case["ticker"], asof, lookback_days=90)
    ta_score, ta_sig = (0.0, {"reason": "no_data"})
    if bars and len(bars) >= 60:
        ta_score, ta_sig = live_score_ta({"bars": bars})

    finra = _hist_finra(case["ticker"], asof)
    insider = _hist_insider_purchases(case["ticker"], asof)

    # SI factor: we only have FINRA + insider components historically,
    # not the structural SI%/DTC snapshot. Score with a stub `fund` that
    # has SI% and DTC=0 so the structural components zero out and only
    # FINRA + insider contribute. (Result is a "lower bound" SI score.)
    si_stub_fund = {"short_percent_of_float": 0, "short_ratio": 0, "shares_short_date": None}
    si_score, si_sig = live_score_si(si_stub_fund, finra, insider)

    regime = _hist_regime(asof)

    available = {"ta": ta_score, "si": si_score}
    flags: list[str] = []
    if ta_sig.get("flag"):
        flags.append(f"ta:{ta_sig['flag']}")
    if si_sig.get("flag"):
        flags.append(f"si:{si_sig['flag']}")

    # Partial composite: average of available factors (each 0-100), then
    # multiply by regime. 100 means everything we COULD measure was
    # maxed; 0 means none of it fired. Note: this is NOT comparable to
    # the live composite (different weighting), only to other partial
    # composites in this report.
    available_vals = [v for v in available.values() if v > 0]
    partial = sum(available_vals) / len(available_vals) if available_vals else 0.0
    partial *= regime.get("multiplier", 1.0)

    return {
        "asof": asof.isoformat(),
        "ta_score": round(ta_score, 1),
        "ta_signals": {k: v for k, v in ta_sig.items() if k in ("breakout", "rvol", "rsi14", "flag")},
        "si_score": round(si_score, 1),
        "si_signals": {
            "finra_latest": (finra or {}).get("latest_short_ratio"),
            "finra_trend": (finra or {}).get("trend"),
            "insider_buy_usd": insider["total_buy_value_usd"],
            "insider_distinct": insider["distinct_insiders"],
            "insider_cluster": insider["cluster_buying"],
            "flag": si_sig.get("flag"),
        },
        "regime": regime.get("regime"),
        "regime_mult": regime.get("multiplier"),
        "partial_composite": round(partial, 1),
        "flags": flags,
        "data_gaps": {
            "ta": bars is None or len(bars or []) < 60,
            "finra": finra is None,
            "regime": regime.get("regime") == "unknown",
        },
    }


def run(samples: list[int] | None = None) -> dict[str, Any]:
    """Run the harness across all cases at T-{samples} days. Returns full report."""
    samples = samples or [30, 14, 7, 3, 1]
    cases_out: list[dict] = []
    for case in SQUEEZE_CASES:
        evals: list[dict] = []
        for t in samples:
            try:
                evals.append({"t_minus": t, **evaluate_case_at(case, t)})
            except Exception as e:
                evals.append({"t_minus": t, "error": str(e)})
        cases_out.append({**case, "evaluations": evals})

    # Aggregate flag-firing rates at each T-N
    flag_aggregate: dict[int, dict[str, int]] = {t: {} for t in samples}
    composites_at: dict[int, list[float]] = {t: [] for t in samples}
    for c in cases_out:
        for ev in c["evaluations"]:
            t = ev["t_minus"]
            if "partial_composite" in ev:
                composites_at[t].append(ev["partial_composite"])
            for f in ev.get("flags", []):
                flag_aggregate[t][f] = flag_aggregate[t].get(f, 0) + 1

    n = len(SQUEEZE_CASES)
    summary_per_t = {}
    for t in samples:
        comps = composites_at[t]
        summary_per_t[t] = {
            "n_evaluated": len(comps),
            "avg_partial_composite": round(sum(comps) / len(comps), 1) if comps else None,
            "median_partial_composite": round(sorted(comps)[len(comps) // 2], 1) if comps else None,
            "pct_above_50": round(sum(1 for v in comps if v >= 50) / max(1, len(comps)) * 100, 1),
            "top_flags": sorted(
                [(f, c, round(c / n * 100, 1)) for f, c in flag_aggregate[t].items()],
                key=lambda x: x[1],
                reverse=True,
            )[:8],
        }

    return {
        "as_of": datetime.utcnow().isoformat() + "Z",
        "n_cases": n,
        "samples": samples,
        "cases": cases_out,
        "summary_per_t": summary_per_t,
    }
