# Perps paper-trading — scope & design

Status: **design only, no code.** Decide from this before building.

## TL;DR
Paper-trading perps is very doable and most of our infrastructure (graph/brain,
ATR + volume levels, bot runner/exit structure, the multiplicative "pressure"
scoring pattern, paper-first discipline) carries over. The two genuinely new
pieces are **(1) a perp-exchange testnet adapter** and **(2) a crypto-native
signal model** — because the equity edge (short interest, options gamma, FINRA,
FTD) does not exist for crypto. Recommended path: **Hyperliquid testnet** +
a **funding/OI/momentum** signal model, built paper-first in 4 small phases.

## Why it's a new module, not a toggle
- **Alpaca has no perps.** Alpaca = equities + options + *spot* crypto. Perps
  require a different venue (a perp exchange testnet).
- **The signals don't transfer.** Our whole edge is equity microstructure. Crypto
  perps have their own microstructure — funding, open interest, liquidations,
  long/short crowding — which is where a crypto edge would come from.

## Venue comparison (paper = testnet)
| Venue | Perps | Testnet | Auth | Notes |
|---|---|---|---|---|
| **Hyperliquid** (rec.) | native | yes, faucet-funded | EVM wallet key (sign requests) | Modern, clean REST/ws, native funding+OI, no KYC, Python SDK. Cleanest first build. |
| **Binance USD-M Futures** | native | yes (testnet.binancefuture.com) | API key/secret (HMAC) | Deepest liquidity + symbol coverage + long/short-ratio data. API is finickier (timestamp/recvWindow, weight limits). |
| **Bybit** | native | yes | API key/secret | Solid API; middle ground. |

Lean **Hyperliquid** for a focused first build (native funding/OI, easy testnet);
**Binance testnet** if you want max realism + the richest positioning data.

## Crypto signal model (the new "edge")
Mirror the equity *pressure* model (multiplicative, "all must fire") with
crypto-native factors — all free from the exchange/public APIs:
- **Funding rate** — the direct short-squeeze analog. Persistently **negative**
  funding + price holding = shorts are crowded and *paying* to stay short →
  squeeze fuel (longs get paid + shorts cover). Extreme **positive** funding =
  crowded longs (fade/long-squeeze risk).
- **Open interest (Δ)** — rising OI + rising price = new longs (trend); rising OI
  + flat/falling price = shorts piling in (fuel).
- **Liquidation proximity** — clustered liq levels above price = a short-squeeze
  cascade target (the crypto forced-cover mechanic).
- **Long/short ratio** (Binance) — crowd positioning extremes = contrarian.
- **Momentum / TA / volume profile** — reuse our existing TA + `levels.py`
  (works on any OHLCV).

Composite idea: `crypto_pressure = funding_pressure × oi_pressure × momentum`,
plus a liquidation-cascade kicker — same shape as the equity L·G·S model.

## Reusable vs new
**Reused as-is:** the knowledge graph / brain (asset-agnostic — crypto trades
feed the same brain with crypto signal nodes), `levels.py` + `risk.py` (ATR /
volume S/R on any OHLCV), the bot runner's exit/risk-cap/kill-switch structure,
the scoring framework, the scan UI patterns, paper-first + accrual validation.

**New:** the perp-exchange adapter (account/positions/order/close, mirroring
`AlpacaClient`), crypto data fetchers (OHLCV, funding, OI, liq), the crypto
signal model + universe, and leverage/liquidation-aware risk.

## The genuinely harder part: leverage & liquidation
Options are **defined-risk** (max loss = premium). Perps are **not** — they're
leveraged and can be **liquidated**. So:
- Sizing must be **risk-based** (position = risk$ / stop-distance) AND
  **leverage-capped**, with the stop set **above the liquidation price** so the
  planned stop triggers first.
- Model **funding cost** over the hold (it accrues every ~8h).
- Crypto trades **24/7** — drop the market-hours gate; add a different cadence.
This is the part to get right; it's where real money dies fastest.

## Phased plan (paper-first, each verifiable)
1. **Adapter** — Hyperliquid (or Binance) testnet: account, positions, submit
   long/short, close, funding/OI reads. Paper-guarded like `AlpacaClient`. + tests.
2. **Data + signals** — OHLCV/funding/OI fetchers → a crypto pressure score +
   a small liquid perp universe (BTC, ETH, SOL, + high-funding/high-OI movers).
3. **Bot wiring** — perp strategy (long/short, leverage-aware sizing,
   liquidation-aware stops, funding-cost awareness), 24/7 runner + caps.
4. **Validate** — paper-track expectancy (accrual-style); the brain ingests the
   crypto trades automatically. Go bigger only if it shows positive expectancy.

## Honest risk note
Same as equities, doubled: **we have no validated crypto edge**, and perps are
leveraged. This stays **paper-only** until measured. The funding-squeeze thesis
is plausible and well-documented, but plausible ≠ profitable — the accrual/graph
loop is what tells us.

## Open decisions for you
1. **Venue:** Hyperliquid testnet (cleanest) vs Binance Futures testnet (realism/data).
2. **Signal scope:** start minimal (funding + OI + momentum) vs fuller (add
   liquidation maps + long/short ratio).
3. **Direction:** long-only "funding squeeze" first (closest to the equity
   thesis), or long/short from the start.
