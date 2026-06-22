"""is_valid_ticker must only block DEFINITIVELY-invalid tickers, never on a
Finnhub hiccup (rate-limit/error/empty) — that was 404'ing valid tickers."""
from src.data import finnhub


def test_blocks_only_zero_price(monkeypatch):
    monkeypatch.setattr(finnhub, "_enabled", lambda: True)

    # valid: price > 0 → allowed
    monkeypatch.setattr(finnhub, "fetch_quote", lambda t: {"current_price": 2.83})
    assert finnhub.is_valid_ticker("AMC") is True

    # definitively invalid: Finnhub returns price 0 → blocked
    monkeypatch.setattr(finnhub, "fetch_quote", lambda t: {"current_price": 0})
    assert finnhub.is_valid_ticker("ZZZZ") is False


def test_does_not_block_on_finnhub_failure(monkeypatch):
    monkeypatch.setattr(finnhub, "_enabled", lambda: True)

    def boom(_t):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(finnhub, "fetch_quote", boom)
    assert finnhub.is_valid_ticker("AMC") is True  # error → don't block

    monkeypatch.setattr(finnhub, "fetch_quote", lambda t: {})
    assert finnhub.is_valid_ticker("AMC") is True  # empty → don't block

    monkeypatch.setattr(finnhub, "fetch_quote", lambda t: {"ticker": "AMC"})
    assert finnhub.is_valid_ticker("AMC") is True  # missing price → don't block


def test_disabled_allows_all(monkeypatch):
    monkeypatch.setattr(finnhub, "_enabled", lambda: False)
    assert finnhub.is_valid_ticker("ANYTHING") is True
