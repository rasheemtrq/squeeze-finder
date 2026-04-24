from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from src.scanner import scan, score_ticker

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
def serve(port: int = 8000, reload: bool = True) -> None:
    """Start FastAPI server."""
    import uvicorn

    uvicorn.run("src.api:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    app()
