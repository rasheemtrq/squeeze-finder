---
name: squeeze-thesis
description: Scoring and ranking formula for short-squeeze candidates. Load when the user asks to run a screen, rank tickers, find squeezes, score candidates, or adjust squeeze weights. Encodes the 5-factor composite (sentiment, options, short interest, technicals, catalysts) and interpretation rules.
---

# Squeeze Thesis — scoring & ranking

## When this skill is active
User says: "run the screen", "find squeezes today", "rank these tickers", "score TICKER", "what's squeezing", "adjust weights".

## Two parallel scores live on every ticker

### A. Composite (linear, 5 factors) — `result.score`
```
score = 0.30 * sentiment + 0.25 * options + 0.20 * si + 0.15 * ta + 0.10 * catalyst
```
Each factor normalized to 0–100 per rules below. Weights overridable via `--weights` CLI flag; default stored in `src/config.py::DEFAULT_WEIGHTS`. Good for ranked discovery and exploration; TA + catalyst add useful confirmation but they trail squeezes, not lead them.

### B. Pressure (multiplicative, 3 pressures) — `result.pressure_score`
Implemented in `src/score/pressure.py`. Research-backed by Allen, Haas, Nowak, Pirovano & Tengulov (2025) "Squeezing Shorts Through Social Media Platforms" + SqueezeMetrics dealer-gamma formulation.
```
pressure = (L_norm · G_norm · S_norm) ** (1/3)      # geometric mean, 0–100
```
Where:
- **L** = (SI%Float / sector_p75) · √(DTC/5) · (FINRA short-vol recent/older) · [institutional_lockup 1.12-1.25x if heldInst≥55% + float<150M]
- **G** = Σ γ(S,K,τ,σ) · OI · 100 · S²  /  (S · float_shares)   for calls with K ∈ [S, 1.15·S], τ ∈ [3, 21]d, OI ≥ 50
- **S** = WSB rank+velocity component  ⊗  StockTwits engagement·polarity component

Geometric mean enforces "all three must fire" — a single-factor candidate (huge social, zero lending) scores ~0 on pressure but might score 50+ on the linear composite. **The pressure score is the academically-validated signal for *imminent* squeezes (1–10 day lead time per Allen et al.).**

Use the two together: linear composite for the watchlist, pressure score for entry timing.

## Factor rubrics

### 1. Sentiment (30%) — StockTwits + Apewisdom WSB
Two sources blended 50/50 when both present:

**StockTwits** (broad retail flow, per-ticker): 24h message volume + bull/bear ratio from paginated stream.
```
volume_score = clip(log2(n/10) * 12, 0, 40)
ratio_score  = (bull_ratio - 0.5) * 80
activity     = 20 if n ≥ 100 else (10 if n ≥ 50 else 0)
st_score     = clip(volume + ratio + activity + 20, 0, 100)
```

**Apewisdom WSB** (squeeze-specific, rank-based): pre-aggregated WSB top-100 mentions with 24h-ago deltas.
```
rank_component = 100 * (101 - min(rank, 100)) / 100    # rank 1 → 100, 100 → 1
velocity_bonus = clip((velocity - 1) * 30, -15, 30)    # velocity = mentions / mentions_24h_ago
rank_momentum  = clip((rank_24h_ago - rank) * 0.5, -10, 15)
wsb_score      = clip(0.7 * rank_component + velocity_bonus + rank_momentum + 10, 0, 100)
```

**Blend:**
- Both present: `0.5 * st + 0.5 * wsb`
- WSB only (ticker not covered by StockTwits): `wsb * 0.85` (single-source penalty)
- StockTwits only (ticker not in WSB top-100): `st_score` — common for large caps, not a penalty; WSB absence just means no squeeze chatter

**Flags:**
- `convergent_bullish`: ST hot + WSB rank ≤20 + rising (highest conviction)
- `wsb_surge`: WSB rank ≤10 AND velocity ≥2 (early squeeze chatter)
- `wsb_fading`: velocity <0.5 (interest collapsing — deprioritize even if price is moving)

### 2. Options / gamma (25%)
Inputs: yfinance options chain — call/put OI, volume, IV skew, near-the-money gamma.
```
cpr       = call_volume_today / put_volume_today        # >2 bullish
oi_spike  = max(near_ATM_call_OI_change_5d) / avg_OI    # >3 = positioning
gamma_conc = near_ATM_call_OI / total_OI                # >0.4 = gamma setup
options   = clip(20*log2(cpr) + 15*log2(oi_spike) + 40*gamma_conc + 10, 0, 100)
```
Flag gamma squeeze setup when: `gamma_conc > 0.4` AND nearest weekly expiry ≤10 days AND spot within 5% of max-gamma strike.

### 3. Short interest (20%)
Inputs: FINRA SI %, days-to-cover.
```
si_pct  = short_shares / float
dtc     = short_shares / 30d_avg_volume
si      = clip(50*min(si_pct/0.30, 1) + 50*min(dtc/10, 1), 0, 100)
```
- `si_pct ≥ 20%` is the entry bar per user thesis
- `dtc ≥ 5` amplifies; `dtc ≥ 10` max
- FINRA data is bi-monthly — note report date in output and penalize if data >20 days old
- **P0 refinement (2026-06)**: institutional_lockup congestion_mult (1.08-1.30x) and pressure L boost when held%inst ≥50-65% + float <100-300M on names with real SI signal. Captures "hard-to-borrow lock-up" from Reddit corpus (high inst ownership + low float = least supply for shorts to cover). Uses yf.heldPercentInstitutions (previously dropped in fetch). Flags as `institutional_lockup` (promoted over generic flags).

### 4. Technicals (15%)
Inputs: OHLCV (yfinance), pandas-ta.
```
breakout = 1 if close > max(high[-60:-1]) else 0    # 60d high break
rvol     = volume_today / 20d_avg_volume
rsi14    = RSI(close, 14)
ta = clip(40*breakout + 30*min(rvol/3, 1) + 30*((rsi14-50)/20 if rsi14<80 else 0), 0, 100)
```
- RSI >80 caps TA score (overextension penalty, not bonus)
- Breakout on `rvol < 1.5` is suspect — halve score

### 5. Catalyst (10%)
Inputs: Finnhub earnings + ClinicalTrials.gov (free) for clinical readouts/PDUFA proxies + dilution/8-K signals.
The fetcher now combines earnings with upcoming clinical events (primary completion, data readouts) from ClinicalTrials.gov — a major free upgrade for biotech-heavy squeeze names.
```
days_to_event = min(earnings_days, clinical_dte, ...)
catalyst = clip(100 * max(0, 1 - days_to_event/30), 0, 100)
```
- Binary events (FDA/clinical readout) get strong scoring.
- Event within 7 days → 75+
- No event within 30 days → 0

## Red flags (auto-demote or exclude)
- Market cap <$50M AND avg daily $volume <$5M → exclude (no liquidity to squeeze)
- Pending reverse split or going-concern disclosure → exclude
- Already up >50% in last 5 sessions → demote 30 points (late to party)
- SEC trading halt active → exclude

## Output contract
Screen output is a ranked table, top 20 by default:
```
rank | ticker | score | sentiment | options | si | ta | catalyst | notes
```
Each factor shown as `score (signal)` e.g., `78 (gamma_setup)`, `62 (breakout_lowvol)`.
Include `data_as_of` timestamps per factor since freshness varies.

## Interpretation rules (for Claude)
- **Do not claim "this will squeeze."** Output is probability-ranked, not prediction.
- A score ≥75 warrants deepdive; 60–75 watchlist; <60 skip.
- If all 5 factors are mid (50–60 each), score looks OK but thesis is weak — flag as "no edge, balanced mediocrity."
- If one factor is ≥90 and others <40, flag as "single-factor bet" — higher variance, lower conviction.

## Invocation
```bash
uv run python -m src.cli scan                    # composite (discovery), top 20
uv run python -m src.cli scan --sort-by pressure # best imminent setups (pressure-ranked)
uv run python -m src.cli scan --min-score 70
uv run python -m src.cli scan --min-pressure 50 --sort-by pressure
uv run python -m src.cli scan --weights 0.4,0.2,0.2,0.1,0.1
uv run python -m src.cli score AMC               # single ticker
```
API: `/api/scan?sort_by=pressure&min_pressure=40` (returns pre-sorted results). Use pressure sort + the geometric L·G·S model when the goal is the highest-conviction short-squeeze *setups* (all three pressures firing) rather than broad high-composite names.
