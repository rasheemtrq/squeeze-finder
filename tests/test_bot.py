"""Bot strategy sizing, plan composition, risk caps, and paper-only guard."""
import pytest

from src.bot import runner, strategy
from src.bot.alpaca import AlpacaClient, AlpacaError
from src.config import BOT_PARAMS

PARAMS = {
    **BOT_PARAMS,
    "risk_pct_per_trade": 1.0,
    "min_setup_score": 50,
    "option_tp_pct": 100,
    "option_sl_pct": 50,
    "time_stop_dte": 7,
    "max_open_positions": 5,
    "max_deploy_pct": 20,
}


def test_occ_symbol():
    assert strategy.occ_symbol("AAPL", "2025-06-20", "call", 200) == "AAPL250620C00200000"
    assert strategy.occ_symbol("SPY", "2025-01-17", "put", 450.5) == "SPY250117P00450500"


def test_size_contracts_defined_risk():
    assert strategy.size_contracts(300, 100_000, 1.0) == 3   # $1000 budget / $300
    assert strategy.size_contracts(1500, 100_000, 1.0) == 0  # premium > budget → skip
    assert strategy.size_contracts(0, 100_000, 1.0) == 0


def _patch_strategy(monkeypatch, contract, levels=None):
    monkeypatch.setattr(strategy, "recommend", lambda t, top_n=5: {"spot": 100, "recommendations": [contract]})
    monkeypatch.setattr(strategy.prices_data, "fetch", lambda t, period="3mo": {"bars": []})
    monkeypatch.setattr(
        strategy, "compute_chart_levels",
        lambda bars: levels or {"entry": 100, "stop": 92, "tp": 120, "rr": 2.5},
    )


def test_plan_for_ticker_composes(monkeypatch):
    _patch_strategy(monkeypatch, {
        "strike": 105, "expiry": "2025-06-20", "dte": 28, "mid": 3.0, "delta": 0.45,
        "iv": 0.6, "open_interest": 1200, "cost_per_contract": 300, "breakeven": 108, "rationale": "x",
    })
    p = strategy.plan_for_ticker("AAPL", 100_000, PARAMS, score=72, pressure=40, flags=["x"])
    assert p["qty"] == 3
    assert p["est_cost"] == 900 and p["risk_usd"] == 900
    assert p["contract"]["occ_symbol"] == "AAPL250620C00105000"
    assert p["exit"]["tp_price"] == 6.0   # +100%
    assert p["exit"]["sl_price"] == 1.5   # -50%
    assert p["underlying"]["tp"] == 120


def test_plan_skips_when_premium_exceeds_budget(monkeypatch):
    _patch_strategy(monkeypatch, {
        "strike": 105, "expiry": "2025-06-20", "dte": 28, "mid": 20.0,
        "delta": 0.45, "open_interest": 1200, "cost_per_contract": 2000,
    })
    assert strategy.plan_for_ticker("AAPL", 100_000, PARAMS) is None


def test_build_plans_filters_score_and_held(monkeypatch):
    monkeypatch.setattr(strategy, "plan_for_ticker", lambda t, eq, params, **kw: {"ticker": t, "est_cost": 500})
    setups = [{"ticker": "AAA", "score": 80}, {"ticker": "BBB", "score": 40}, {"ticker": "CCC", "score": 90}]
    plans = strategy.build_plans(setups, 100_000, PARAMS, skip_tickers={"CCC"})
    assert [p["ticker"] for p in plans] == ["AAA"]  # BBB < min score, CCC held


def test_apply_risk_caps_max_positions():
    plans = [{"ticker": f"T{i}", "est_cost": 3000} for i in range(8)]
    kept, _dropped, deployed = runner.apply_risk_caps(plans, 100_000, PARAMS, open_count=0)
    assert len(kept) == 5 and deployed == 15000          # positions cap binds
    kept2, _, _ = runner.apply_risk_caps(plans, 100_000, PARAMS, open_count=4)
    assert len(kept2) == 1                                # only 1 slot left


def test_apply_risk_caps_deploy_binds():
    plans = [{"ticker": f"T{i}", "est_cost": 9000} for i in range(5)]
    kept, _, deployed = runner.apply_risk_caps(plans, 100_000, PARAMS, open_count=0)
    assert len(kept) == 2 and deployed == 18000          # deploy cap (20k) binds before positions


def test_occ_parsing_helpers():
    assert runner._underlying_of("AAPL250620C00200000") == "AAPL"
    assert runner._dte_from_occ("AAPL") is None          # stock symbol, not an option
    d = runner._dte_from_occ("AAPL250620C00200000")
    assert d is None or isinstance(d, int)


def test_alpaca_refuses_live():
    with pytest.raises(AlpacaError):
        AlpacaClient(paper=False)
