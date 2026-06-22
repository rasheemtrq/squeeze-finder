"""Unit tests for the liquid swing universe builder."""
from src.data import liquid_universe as lu


def test_normalize_class_shares():
    assert lu._normalize("brk.b") == "BRK-B"
    assert lu._normalize(" aapl ") == "AAPL"
    assert lu._normalize("BF.B") == "BF-B"


def test_assemble_dedups_and_tags_sources():
    res = lu._assemble(["AAPL", "MSFT", "RKLB"])  # RKLB also in the supplement
    t = res["tickers"]
    assert "AAPL" in t and "MSFT" in t
    assert t.count("RKLB") == 1  # dedup across sources
    assert "AAPL" in res["sources"]["sp500"]
    assert "ASTS" in t  # supplement-only name pulled in


def test_assemble_excludes_index_etfs():
    res = lu._assemble(["SPY", "AAPL", "QQQ"])
    assert "SPY" not in res["tickers"]
    assert "QQQ" not in res["tickers"]
    assert "AAPL" in res["tickers"]


def test_build_falls_back_when_fetch_fails(monkeypatch):
    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(lu, "_fetch_sp500", boom)
    monkeypatch.setattr(lu._cache, "get", lambda *a, **k: None)
    res = lu.build(force_refresh=True)
    assert "fallback" in res
    assert len(res["tickers"]) > 0
    assert "RKLB" in res["tickers"]  # supplement + core keep the scan alive
