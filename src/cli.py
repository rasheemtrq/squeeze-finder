from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from src.research.historical_squeezes import run as run_historical_squeezes
from src.scanner import scan, score_ticker
from src.score.backtest import evaluate as backtest_evaluate

app = typer.Typer(help="squeeze-finder CLI")
console = Console()


@app.command()
def scan_cmd(
    limit: int = 20,
    min_score: float = 0,
    tickers: str | None = typer.Option(None, help="comma-separated override"),
) -> None:
    """Run the squeeze scan."""
    universe = [t.strip().upper() for t in tickers.split(",")] if tickers else None
    with console.status("scanning..."):
        result = scan(tickers=universe, min_score=min_score, limit=limit)

    table = Table(title=f"top {result['returned']} of {result['scored']} scored")
    table.add_column("rank")
    table.add_column("ticker")
    table.add_column("score", justify="right")
    table.add_column("sent", justify="right")
    table.add_column("opts", justify="right")
    table.add_column("si", justify="right")
    table.add_column("ta", justify="right")
    table.add_column("cat", justify="right")
    table.add_column("flags")
    for i, r in enumerate(result["results"], 1):
        f = r["factors"]
        table.add_row(
            str(i),
            r["ticker"],
            f"{r['score']}",
            f"{f['sentiment']['score']}",
            f"{f['options']['score']}",
            f"{f['si']['score']}",
            f"{f['ta']['score']}",
            f"{f['catalyst']['score']}",
            ", ".join(r["flags"]),
        )
    console.print(table)


@app.command()
def analyze(ticker: str) -> None:
    """Score a single ticker."""
    result = score_ticker(ticker.upper())
    console.print_json(json.dumps(result, default=str))


@app.command()
def backtest(window: int = typer.Option(5, help="forward-return window in calendar days")) -> None:
    """Hit-rate by score-decile across historical scan snapshots."""
    result = backtest_evaluate(window_days=window)
    if not result["evaluated"]:
        console.print(f"[yellow]{result.get('note', 'no data')}[/yellow]")
        console.print(f"snapshots scanned: {result['snapshots']}")
        return

    console.print(
        f"[bold]forward-return window:[/bold] {result['window_days']}d  ·  "
        f"snapshots: {result['snapshots']}  ·  evaluated: {result['evaluated']}"
    )

    table = Table(title="hit-rate by composite-score decile")
    table.add_column("decile")
    table.add_column("n", justify="right")
    table.add_column("score range")
    table.add_column("avg ret %", justify="right")
    table.add_column("median ret %", justify="right")
    table.add_column("win rate", justify="right")
    table.add_column("≥50% drawup", justify="right")
    for d in result["deciles"]:
        table.add_row(
            str(d["decile"]),
            str(d["n"]),
            f"{d['score_range'][0]}–{d['score_range'][1]}",
            f"{d['avg_return_pct']:+.2f}",
            f"{d['median_return_pct']:+.2f}",
            f"{d['win_rate']:.0%}",
            f"{d['pct_with_50pct_drawup']:.0%}",
        )
    console.print(table)

    if result.get("flag_performance"):
        ftable = Table(title="flag-level performance (n≥5)")
        ftable.add_column("flag")
        ftable.add_column("n", justify="right")
        ftable.add_column("avg ret %", justify="right")
        ftable.add_column("win rate", justify="right")
        for r in result["flag_performance"]:
            ftable.add_row(r["flag"], str(r["n"]), f"{r['avg_return_pct']:+.2f}", f"{r['win_rate']:.0%}")
        console.print(ftable)


@app.command()
def research_squeezes(
    samples: str = typer.Option("30,14,7,3,1", help="comma-separated T-N days before squeeze"),
    output: str | None = typer.Option(None, help="if set, write full JSON to this path"),
) -> None:
    """Replay scoring on the days BEFORE famous historical squeezes.

    Honest caveat: only TA, FINRA short-volume, insider Form 4, and regime
    are historically replayable on free data. Sentiment, structural SI%, and
    options chain IV/gamma have no public archive — those factors will read
    as 0/None per case. The 'partial_composite' is the average of factors
    we CAN replay, not the live composite.
    """
    sample_list = [int(s.strip()) for s in samples.split(",")]
    with console.status("running historical squeeze backtest (this hits SEC EDGAR + yfinance per case)..."):
        report = run_historical_squeezes(samples=sample_list)

    console.print(f"[bold]historical squeeze replay[/bold] · {report['n_cases']} cases · samples T-{sample_list}")
    console.print()

    for c in report["cases"]:
        console.print(f"[bold]{c['ticker']}[/bold] · squeeze {c['squeeze_date']} · peak +{c['peak_return_pct']}% · {c['notes']}")
        t = Table()
        t.add_column("T-N")
        t.add_column("as-of")
        t.add_column("ta", justify="right")
        t.add_column("si", justify="right")
        t.add_column("regime")
        t.add_column("partial", justify="right")
        t.add_column("flags")
        for ev in c["evaluations"]:
            if "error" in ev:
                t.add_row(f"T-{ev['t_minus']}", "—", "—", "—", "—", "ERROR", ev["error"][:60])
                continue
            t.add_row(
                f"T-{ev['t_minus']}",
                ev["asof"],
                f"{ev['ta_score']}",
                f"{ev['si_score']}",
                ev.get("regime") or "—",
                f"{ev['partial_composite']}",
                ", ".join(ev["flags"]) or "—",
            )
        console.print(t)
        console.print()

    console.print("[bold]aggregate by T-N[/bold]")
    agg = Table()
    agg.add_column("T-N")
    agg.add_column("n", justify="right")
    agg.add_column("avg partial", justify="right")
    agg.add_column("median", justify="right")
    agg.add_column("% ≥50", justify="right")
    agg.add_column("top flags (n / %)")
    for t_n, s in sorted(report["summary_per_t"].items(), reverse=True):
        flags_str = ", ".join(f"{f}:{c}({pct}%)" for f, c, pct in s["top_flags"][:5])
        agg.add_row(
            f"T-{t_n}",
            str(s["n_evaluated"]),
            str(s["avg_partial_composite"]),
            str(s["median_partial_composite"]),
            f"{s['pct_above_50']}%",
            flags_str or "—",
        )
    console.print(agg)

    if output:
        from pathlib import Path
        Path(output).write_text(json.dumps(report, indent=2, default=str))
        console.print(f"[green]wrote full JSON to {output}[/green]")


@app.command()
def serve(port: int = 8000, reload: bool = True) -> None:
    """Start FastAPI server."""
    import uvicorn

    uvicorn.run("src.api:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    app()
