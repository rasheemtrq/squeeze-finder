from __future__ import annotations

import json
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Table

from src.research.historical_squeezes import run as run_historical_squeezes
from src.research.reddit_strategies import run as run_reddit_strategies
from src.scanner import scan, score_ticker
from src.score.backtest import evaluate as backtest_evaluate
from src.score.calibration import evaluate as calibration_evaluate

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
def calibration(
    window: int = typer.Option(5, help="forward-return window in calendar days"),
    threshold: float = typer.Option(10.0, help='win threshold: max drawup ≥ this % counts as a "win"'),
    buckets: int = typer.Option(10, help="reliability diagram resolution"),
) -> None:
    """Brier-score decomposition + reliability diagram for composite & pressure."""
    report = calibration_evaluate(window_days=window, win_threshold_pct=threshold, n_buckets=buckets)
    if report.get("evaluated", 0) == 0:
        console.print(f"[yellow]{report.get('note', 'no data')}[/yellow]")
        console.print(f"snapshots scanned: {report.get('snapshots', 0)}")
        return

    s = report["settings"]
    console.print(
        f"[bold]calibration[/bold]  window={s['window_days']}d  "
        f"win=Δ+{s['win_threshold_pct']}%  buckets={s['n_buckets']}  "
        f"evaluated={report['evaluated']}"
    )

    for model_name in ("composite", "pressure"):
        m = report.get(model_name) or {}
        if not m.get("n"):
            console.print(f"\n[bold]{model_name}[/bold]  [yellow](no data)[/yellow]")
            continue
        console.print(
            f"\n[bold]{model_name}[/bold]  base_rate={m.get('base_rate'):.3f}  "
            f"brier={m.get('brier'):.4f}  reliability↓={m.get('reliability'):.4f}  "
            f"resolution↑={m.get('resolution'):.4f}  skill={m.get('skill'):+.4f}  "
            f"lift@top={m.get('lift_at_top_decile')}x  "
            f"IC(score↔ret)={m.get('spearman_ic_score_vs_return')}"
        )
        if m.get("buckets"):
            t = Table(title=f"{model_name} reliability diagram")
            t.add_column("bucket")
            t.add_column("score range")
            t.add_column("n", justify="right")
            t.add_column("predicted p", justify="right")
            t.add_column("realized hit", justify="right")
            t.add_column("gap", justify="right")
            for b in m["buckets"]:
                gap = b["gap"]
                gap_color = "red" if abs(gap) > 0.15 else ("yellow" if abs(gap) > 0.05 else "green")
                t.add_row(
                    str(b["bucket"]),
                    f"{b['score_range_pct'][0]:.0f}–{b['score_range_pct'][1]:.0f}",
                    str(b["n"]),
                    f"{b['predicted_p']:.2f}",
                    f"{b['realized_hit_rate']:.2f}",
                    f"[{gap_color}]{gap:+.2f}[/{gap_color}]",
                )
            console.print(t)


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
def research_reddit(
    per_source_limit: int = typer.Option(25, help="top N posts per (subreddit, query)"),
    no_comments: bool = typer.Option(False, help="skip top-comments fetch (faster)"),
    output: str = typer.Option("data/research/reddit_strategies.json", help="JSON output path"),
    harvest_only: bool = typer.Option(False, help="only scrape; skip Haiku synthesis (use when no API key)"),
    synthesize_from: str | None = typer.Option(None, help="skip scrape; load corpus from this JSON path and only synthesize"),
) -> None:
    """Scrape Reddit for 0DTE + squeeze trading patterns and synthesize via Haiku.

    Honest caveat: Reddit posts are heavily survivorship-biased. Output surfaces
    patterns people TALK about, not necessarily patterns that statistically work.
    Use the synthesis to identify GAPS in what we already model, not as ground truth.
    """
    from pathlib import Path

    from src.research.reddit_strategies import harvest as reddit_harvest
    from src.research.reddit_strategies import synthesize_with_haiku
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if synthesize_from:
        with console.status(f"loading corpus from {synthesize_from} and synthesizing with Haiku..."):
            corpus = json.loads(Path(synthesize_from).read_text())
            # corpus may be a full prior report or just a harvest; handle both
            harvest_data = corpus.get("harvest_data") or corpus
            if "posts" not in harvest_data and "raw_corpus" in corpus:
                harvest_data = {"posts": corpus["raw_corpus"], "n_in_corpus": len(corpus["raw_corpus"])}
            synthesis = synthesize_with_haiku(harvest_data)
            report = {
                "as_of": datetime.now(UTC).isoformat(),
                "synthesis": synthesis,
                "raw_corpus": harvest_data["posts"],
                "harvest": {"n_in_corpus": len(harvest_data["posts"])},
            }
    elif harvest_only:
        with console.status("scraping Reddit only (no synthesis)..."):
            harvest_data = reddit_harvest(per_source_limit=per_source_limit, with_comments=not no_comments)
            report = {"harvest_data": harvest_data}
        out_path.write_text(json.dumps(report, indent=2, default=str))
        console.print(f"[green]wrote harvest-only corpus to {out_path}[/green]")
        console.print("Run with --synthesize-from <path> on a machine with OPENROUTER_API_KEY to complete.")
        return
    else:
        with console.status("scraping Reddit + synthesizing with Haiku (60-90s)..."):
            report = run_reddit_strategies(
                per_source_limit=per_source_limit,
                with_comments=not no_comments,
            )

    out_path.write_text(json.dumps(report, indent=2, default=str))
    console.print(f"[green]wrote full report to {out_path}[/green]")
    console.print()

    syn = report["synthesis"]
    console.print(f"[bold]reddit strategy synthesis[/bold] · {report['harvest']['n_in_corpus']} posts analyzed by {syn.get('model_used', '?')}")
    console.print()

    for section_name in ("zero_dte", "squeezes"):
        section = syn.get(section_name) or {}
        if not section:
            continue
        console.print(f"[bold cyan]{section_name.upper().replace('_', ' ')}[/bold cyan]")
        for subkey in ("entry_setups", "entry_triggers", "screening_criteria", "exit_rules", "risk_mgmt"):
            items = section.get(subkey) or []
            if not items:
                continue
            console.print(f"  [bold]{subkey}:[/bold]")
            for it in items:
                evidence = it.get("evidence_count")
                marker = f" ({evidence}×)" if evidence else ""
                console.print(f"    • [yellow]{it.get('name', '?')}[/yellow]{marker}: {it.get('what', '')}")
        failures = section.get("common_failures") or []
        if failures:
            console.print("  [bold red]common failures:[/bold red]")
            for f in failures:
                console.print(f"    × {f}")
        console.print()

    if syn.get("data_sources_mentioned"):
        console.print(f"[bold]data sources mentioned:[/bold] {', '.join(syn['data_sources_mentioned'])}")
    if syn.get("tools_mentioned"):
        console.print(f"[bold]tools mentioned:[/bold] {', '.join(syn['tools_mentioned'])}")
    if syn.get("honest_caveats"):
        console.print()
        console.print(f"[dim italic]{syn['honest_caveats']}[/dim italic]")


@app.command()
def serve(port: int = 8000, reload: bool = True) -> None:
    """Start FastAPI server."""
    import uvicorn

    uvicorn.run("src.api:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    app()
