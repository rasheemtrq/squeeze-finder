from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

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
def serve(port: int = 8000, reload: bool = True) -> None:
    """Start FastAPI server."""
    import uvicorn

    uvicorn.run("src.api:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    app()
