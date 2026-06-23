from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.config import FINNHUB_API_KEY
from src.research.historical_squeezes import run as run_historical_squeezes
from src.research.reddit_strategies import run as run_reddit_strategies
from src.scanner import scan, score_ticker
from src.score.backtest import evaluate as backtest_evaluate
from src.score.calibration import evaluate as calibration_evaluate
from src.score.swing_backtest import evaluate as swing_backtest_evaluate
from src.swing_scanner import swing_scan

app = typer.Typer(help="squeeze-finder CLI")
console = Console()


@app.command()
def scan_cmd(
    limit: int = 20,
    min_score: float = 0,
    min_pressure: float = 0,
    sort_by: str = typer.Option("composite", "--sort-by", help="composite (default) or pressure for imminent setups"),
    tickers: str | None = typer.Option(None, help="comma-separated override"),
    timings: bool = typer.Option(False, "--timings", help="Show per-source fetch timings"),
    alphavantage: bool = typer.Option(
        False, "--alphavantage", help="Enrich top results with Alpha Vantage (fundamentals + news) - uses free tier"
    ),
) -> None:
    """Run the squeeze scan. Use --sort-by pressure to rank best short squeeze setups by the multiplicative pressure model (L·G·S)."""
    universe = [t.strip().upper() for t in tickers.split(",")] if tickers else None
    with console.status("scanning..."):
        result = scan(
            tickers=universe,
            min_score=min_score,
            min_pressure=min_pressure,
            limit=limit,
            sort_by=sort_by,
        )

    sort_label = "pressure" if sort_by in ("pressure", "pressure_score") else "composite"
    title = f"top {result['returned']} of {result['scored']} · sort={sort_label} · min_score={min_score} min_pressure={min_pressure}"
    if alphavantage:
        title += " · +alphavantage"
    if FINNHUB_API_KEY:
        title += " · +finnhub"
    table = Table(title=title)
    table.add_column("rank", justify="right")
    table.add_column("ticker")
    table.add_column("score", justify="right")
    table.add_column("press", justify="right")
    table.add_column("cat", justify="right")
    table.add_column("cat_kind", justify="left")
    table.add_column("ftd", justify="right")
    table.add_column("flags")
    for i, r in enumerate(result["results"], 1):
        f = r["factors"]
        ps = r.get("pressure_score") or {}
        pscore = ps.get("score", "–") if isinstance(ps, dict) else "–"
        cat = f.get("catalyst", {})
        cat_score = cat.get("score", "–")
        cat_kind = (cat.get("signals") or {}).get("kind") or (r.get("catalysts") or {}).get("kind") or ""
        ftd_data = (r.get("ftd") or {})
        ftd_str = str(ftd_data.get("latest_ftd", "–")) if ftd_data.get("latest_ftd") else "–"
        table.add_row(
            str(i),
            r["ticker"],
            f"{r['score']}",
            f"{pscore}",
            f"{cat_score}",
            cat_kind[:12],
            ftd_str,
            ", ".join(r["flags"])[:50],
        )
    console.print(table)


@app.command()
def analyze(ticker: str) -> None:
    """Score a single ticker with explanation of why it ranks."""
    result = score_ticker(ticker.upper())
    console.print_json(json.dumps(result, default=str))

    # Simple "why" explanation
    if not result.get("excluded"):
        f = result.get("factors", {})
        flags = result.get("flags", [])
        ps = result.get("pressure_score", {})
        top_factors = sorted(
            [(k, v.get("score", 0)) for k, v in f.items()],
            key=lambda x: x[1], reverse=True
        )[:3]
        explanation = f"Top drivers: {', '.join([f'{k}:{s}' for k,s in top_factors])}. "
        if ps.get("score", 0) > 40:
            explanation += "Strong pressure (L·G·S) — good for timing. "
        if any("ftd" in str(fl).lower() or "settlement" in str(fl).lower() for fl in flags):
            explanation += "FTD pressure detected (best free signal). "
        if any("clinical" in str(fl).lower() or "fda" in str(fl).lower() for fl in flags):
            explanation += "Clinical catalyst in window. "
        console.print(f"\n[bold cyan]Why {ticker.upper()} ranks:[/bold cyan] {explanation}")


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
def ftd(refresh: bool = typer.Option(False, "--refresh", help="Download latest SEC FTD files and rebuild local index"),
        force: bool = typer.Option(False, "--force", help="Force re-download even if files exist")) -> None:
    """Manage the SEC Fails-to-Deliver (FTD) dataset — one of the best free signals for settlement pressure."""
    from src.data import ftd as ftd_mod

    if refresh:
        with console.status("Refreshing SEC FTD data (this can take a minute on first run)..."):
            result = ftd_mod.refresh(force=force)
        console.print("[green]FTD refresh complete[/green]")
        console.print(f"  Downloaded: {result.get('downloaded', [])}")
        console.print(f"  Tickers in index: {result.get('index_tickers', 0)}")
        console.print(f"  as_of: {result.get('as_of')}")
    else:
        console.print("FTD data is a bulk official SEC dataset (published ~2× per month).")
        console.print("Run with --refresh to ingest the latest available files.")
        console.print("The scanner will then use fast local lookups automatically.")


@app.command("swing")
def swing_cmd(
    limit: int = 20,
    min_score: float = 0,
    tickers: str | None = typer.Option(None, help="comma-separated override"),
    mode: str = typer.Option("liquid", "--mode", help="liquid (S&P500+leaders), dynamic (meme/WSB), or core"),
    prefilter: int = typer.Option(60, "--prefilter", help="Stage-1 survivors enriched in liquid mode"),
) -> None:
    """Run the SWING scan (2-4 week trend-continuation holds) with trade plans.

    Each result carries an ATR-based plan: entry, stop under structural support,
    R-multiple targets, and an account-risk-normalized position size. Ranked by
    the swing composite, nudged toward tight-risk (high R:R) setups.
    """
    universe = [t.strip().upper() for t in tickers.split(",")] if tickers else None
    with console.status("swing scanning..."):
        result = swing_scan(
            tickers=universe,
            min_score=min_score,
            limit=limit,
            universe_mode=mode,
            prefilter_n=prefilter,
        )

    reg = result.get("regime") or {}
    pf = f" · prefiltered {result['universe_size']}→{result['prefiltered_to']}" if result.get("prefiltered_to") else ""
    title = (
        f"swing [{result.get('universe_mode', mode)}] · top {result['returned']} of {result['scored']}{pf} · "
        f"regime={reg.get('regime', '?')} (×{reg.get('multiplier', 1.0)})"
    )
    table = Table(title=title)
    for col, just in [
        ("rank", "right"), ("ticker", "left"), ("score", "right"),
        ("st", "right"), ("bo", "right"), ("rs", "right"),
        ("entry", "right"), ("stop", "right"), ("risk%", "right"),
        ("T(3R)", "right"), ("pos%", "right"), ("flags", "left"),
    ]:
        table.add_column(col, justify=just)

    for i, r in enumerate(result["results"], 1):
        f = r["factors"]
        p = r.get("trade_plan") or {}
        targets = p.get("targets") or [None, None]
        table.add_row(
            str(i),
            r["ticker"],
            f"{r['score']}",
            f"{f['stage2']['score']:.0f}",
            f"{f['breakout']['score']:.0f}",
            f"{f['rs']['score']:.0f}",
            f"{p.get('entry', '–')}",
            f"{p.get('stop', '–')}",
            f"{p.get('risk_pct', '–')}",
            f"{targets[-1] if targets[-1] else '–'}",
            f"{p.get('position_pct', '–')}",
            ", ".join(r["flags"])[:46],
        )
    console.print(table)
    console.print(
        "[dim]pos% = allocation that risks 1% of account if the stop hits. "
        "Plans are mechanical, not advice — size to your own risk budget.[/dim]"
    )


@app.command("swing-backtest")
def swing_backtest_cmd(
    window: int = typer.Option(14, help="hold window in calendar days (try 10 and 20 for 2-4wk)"),
) -> None:
    """Realized expectancy (in R) + final-return by swing-score decile.

    Replays each recorded swing pick against forward bars: stop first (−1R),
    target first (+R), or mark-to-market at the horizon. Says UNDERPOWERED
    until enough scan-days have accrued to mean anything.
    """
    result = swing_backtest_evaluate(window_days=window)
    if not result.get("evaluated"):
        console.print(f"[yellow]{result.get('note', 'no data')}[/yellow]")
        console.print(f"snapshots scanned: {result.get('snapshots', 0)}")
        return

    o = result.get("overall_expectancy") or {}
    console.print(
        f"[bold]swing backtest[/bold]  window={result['window_days']}d  "
        f"evaluated={result['evaluated']}  scan-days={result.get('scan_days')}"
    )
    console.print(
        f"expectancy={o.get('expectancy_r', '–')}R  win_rate={o.get('win_rate_r', '–')}  "
        f"avg_win={o.get('avg_win_r', '–')}R  avg_loss={o.get('avg_loss_r', '–')}R  "
        f"stop_rate={o.get('stop_rate', '–')}  "
        f"IC(score↔ret)={result.get('spearman_ic_score_vs_return')}  "
        f"top-decile lift={result.get('top_decile_expectancy_lift')}x"
    )
    if result.get("note"):
        console.print(f"[yellow]{result['note']}[/yellow]")

    table = Table(title="expectancy by swing-score decile")
    for col in ["decile", "n", "score range", "avg ret %", "win rate", "exp (R)", "stop %", "target %", "avg DD %"]:
        table.add_column(col, justify="right" if col != "score range" else "left")
    for d in result["deciles"]:
        table.add_row(
            str(d["decile"]), str(d["n"]),
            f"{d['score_range'][0]}–{d['score_range'][1]}",
            f"{d['avg_return_pct']:+.2f}",
            f"{d['win_rate']:.0%}",
            f"{d['expectancy_r'] if d['expectancy_r'] is not None else '–'}",
            f"{d['stop_rate']:.0%}" if d['stop_rate'] is not None else "–",
            f"{d['target_rate']:.0%}" if d['target_rate'] is not None else "–",
            f"{d['avg_max_drawdown_pct']:+.1f}",
        )
    console.print(table)

    if result.get("flag_performance"):
        ftable = Table(title="flag-level expectancy (n≥5)")
        for col in ["flag", "n", "avg ret %", "exp (R)"]:
            ftable.add_column(col, justify="right" if col != "flag" else "left")
        for r in result["flag_performance"]:
            ftable.add_row(
                r["flag"], str(r["n"]), f"{r['avg_return_pct']:+.2f}",
                f"{r['expectancy_r'] if r['expectancy_r'] is not None else '–'}",
            )
        console.print(ftable)


@app.command("accrue")
def accrue_cmd(
    with_squeeze: bool = typer.Option(False, "--with-squeeze", help="also run + record the squeeze scan"),
) -> None:
    """Run scans and record forward-return snapshots. The daily fidelity engine.

    Wire this to a daily cron (market days, after close). Each run records one
    snapshot per scored name; the backtest reads them once they age past the
    hold window. This accrual is the only thing that makes the scanner
    high-fidelity — free data has no history to backtest these signals against.
    """
    swing = swing_scan(force_refresh=True, universe_mode="liquid", limit=200, prefilter_n=80)
    console.print(
        f"[green]swing[/green] mode={swing.get('universe_mode')} "
        f"universe={swing['universe_size']} prefiltered→{swing.get('prefiltered_to')} "
        f"scored={swing['scored']} · recorded snapshot for {swing['as_of'][:10]}"
    )
    if with_squeeze:
        sq = scan(force_refresh=True, limit=200)
        console.print(f"[green]squeeze[/green] scored={sq['scored']} recorded snapshot")


@app.command("bot-plan")
def bot_plan_cmd(limit: int = 15) -> None:
    """Dry-run: build today's paper-bot options plan (no orders placed)."""
    from src.bot.runner import run

    with console.status("building bot plan (scan + options)..."):
        plan = run(execute=False, limit=limit)
    console.print(
        f"[bold]bot plan[/bold] · equity ${plan['equity']:,.0f} · "
        f"scanned {plan['scanned']} · candidates {plan['candidates']} · "
        f"deploy ${plan['deployed_usd']:,.0f}/${plan['deploy_cap_usd']:,.0f}"
    )
    if not plan["selected"]:
        console.print("[yellow]no qualifying setups (check min score / risk caps)[/yellow]")
        return
    table = Table(title="paper bot — long-call plan (DRY RUN, no orders)")
    for col in ["#", "ticker", "score", "contract", "dte", "qty", "est cost", "Δ", "entry", "opt SL→TP"]:
        table.add_column(col, justify="left" if col in ("ticker", "contract") else "right")
    for i, p in enumerate(plan["selected"], 1):
        c, e = p["contract"], p["exit"]
        table.add_row(
            str(i), p["ticker"], f"{p['setup_score']}",
            f"${c['strike']:g} {c['expiry'][5:]}", f"{c['dte']}", str(p["qty"]),
            f"${p['est_cost']:,.0f}", f"{c['delta']:.2f}" if c.get("delta") else "–",
            f"${(p['underlying'].get('entry') or 0):.2f}",
            f"${e['sl_price']:g}→${e['tp_price']:g}",
        )
    console.print(table)
    console.print(
        "[dim]long calls · risk = premium paid · add ALPACA_API_KEY/SECRET (paper) "
        "then `bot-run --execute` to place PAPER orders[/dim]"
    )


@app.command("bot-status")
def bot_status_cmd() -> None:
    """Alpaca PAPER account + open positions."""
    from src.bot.alpaca import AlpacaClient, AlpacaError

    try:
        client = AlpacaClient()
        acct = client.account()
        pos = client.positions()
    except AlpacaError as e:
        console.print(f"[yellow]{e}[/yellow]")
        return
    eq, last = float(acct["equity"]), float(acct.get("last_equity") or acct["equity"])
    day_pl = (eq - last) / last * 100 if last else 0.0
    console.print(
        f"[bold]paper account[/bold] equity ${eq:,.2f} · cash ${float(acct['cash']):,.2f} · "
        f"day P/L {day_pl:+.2f}%"
    )
    if not pos:
        console.print("no open positions")
        return
    t = Table(title="open positions")
    for col in ["symbol", "qty", "avg cost", "mkt value", "P/L %"]:
        t.add_column(col, justify="left" if col == "symbol" else "right")
    for p in pos:
        t.add_row(
            p["symbol"], p["qty"], f"${float(p.get('avg_entry_price', 0)):.2f}",
            f"${float(p.get('market_value', 0)):,.2f}",
            f"{float(p.get('unrealized_plpc', 0)) * 100:+.1f}%",
        )
    console.print(t)


@app.command("bot-run")
def bot_run_cmd(
    execute: bool = typer.Option(False, "--execute", help="place PAPER orders + manage exits (default: dry run)"),
    limit: int = 15,
) -> None:
    """Run one bot cycle. Default is a dry run; --execute places PAPER orders."""
    from src.bot.alpaca import AlpacaError
    from src.bot.runner import run

    if not execute:
        bot_plan_cmd(limit=limit)
        return
    with console.status("running bot cycle (paper execute)..."):
        try:
            res = run(execute=True, limit=limit)
        except AlpacaError as e:
            console.print(f"[yellow]{e}[/yellow]")
            return
    console.print_json(json.dumps(res, default=str))


@app.command("crypto-scan")
def crypto_scan_cmd(limit: int = 15) -> None:
    """Rank the spot-crypto universe by momentum (trend + breakout + RS vs BTC)."""
    from src.crypto.scanner import scan_crypto

    with console.status("scanning crypto momentum..."):
        res = scan_crypto(limit=limit)
    console.print(
        f"[bold]crypto momentum[/bold] · universe {res['universe']} · scored {res['scored']}"
    )
    if not res["results"]:
        console.print("[yellow]no coins scored (check data availability)[/yellow]")
        return
    table = Table(title="spot crypto — momentum scan")
    for col in ["#", "pair", "score", "price", "trend", "breakout", "RS", "rvol", "entry→stop→TP"]:
        table.add_column(col, justify="left" if col == "pair" else "right")
    for i, r in enumerate(res["results"], 1):
        f, lv = r["factors"], r["levels"]
        table.add_row(
            str(i), r["ticker"], f"{r['score']}", f"${r['price']:,.4g}",
            f"{f['trend']['score']:.0f}", f"{f['breakout']['score']:.0f}",
            f"{f['rs_vs_btc']['score']:.0f}",
            f"{f['breakout'].get('rvol') or 0:.1f}",
            f"${lv['entry']:g}→${lv['stop']:g}→${lv['tp']:g}",
        )
    console.print(table)


@app.command("crypto-plan")
def crypto_plan_cmd(limit: int = 15) -> None:
    """Dry-run: build today's paper-bot spot-crypto plan (no orders placed)."""
    from src.crypto.runner import run

    with console.status("building crypto plan (scan + sizing)..."):
        plan = run(execute=False, limit=limit)
    console.print(
        f"[bold]crypto plan[/bold] · equity ${plan['equity']:,.0f} · "
        f"scanned {plan['scanned']} · candidates {plan['candidates']} · "
        f"deploy ${plan['deployed_usd']:,.0f}/${plan['deploy_cap_usd']:,.0f}"
    )
    if not plan["selected"]:
        console.print("[yellow]no qualifying setups (check min score / risk caps)[/yellow]")
        return
    table = Table(title="paper bot — spot crypto plan (DRY RUN, no orders)")
    for col in ["#", "pair", "score", "notional", "risk $", "entry", "stop", "TP", "R:R"]:
        table.add_column(col, justify="left" if col == "pair" else "right")
    for i, p in enumerate(plan["selected"], 1):
        u = p["underlying"]
        table.add_row(
            str(i), p["ticker"], f"{p['setup_score']}", f"${p['notional']:,.0f}",
            f"${p['risk_usd']:,.0f}", f"${(u.get('entry') or 0):g}",
            f"${(u.get('stop') or 0):g}", f"${(u.get('tp') or 0):g}",
            f"{u.get('rr') or 0:.1f}",
        )
    console.print(table)
    console.print(
        "[dim]spot long · risk = notional × stop% · 24/7 · "
        "`crypto-run --execute` to place PAPER orders[/dim]"
    )


@app.command("crypto-run")
def crypto_run_cmd(
    execute: bool = typer.Option(False, "--execute", help="place PAPER spot orders + manage exits (default: dry run)"),
    limit: int = 15,
) -> None:
    """Run one crypto bot cycle. Default is a dry run; --execute places PAPER orders."""
    from src.bot.alpaca import AlpacaError
    from src.crypto.runner import run

    if not execute:
        crypto_plan_cmd(limit=limit)
        return
    with console.status("running crypto bot cycle (paper execute)..."):
        try:
            res = run(execute=True, limit=limit)
        except AlpacaError as e:
            console.print(f"[yellow]{e}[/yellow]")
            return
    console.print_json(json.dumps(res, default=str))


@app.command("crypto-scalp")
def crypto_scalp_cmd(
    execute: bool = typer.Option(False, "--execute", help="place PAPER scalp orders + manage exits (default: dry run)"),
) -> None:
    """Intraday crypto scalp cycle (1-min momentum). Default dry run; --execute trades PAPER.

    Built to fire every ~60s. Take-profits are sized to clear Alpaca's ~0.5%
    round-trip fee; outcomes are logged net of cost. 24/7."""
    from src.bot.alpaca import AlpacaError
    from src.crypto.scalp_runner import run

    with console.status("running crypto scalp cycle..."):
        try:
            res = run(execute=execute)
        except AlpacaError as e:
            console.print(f"[yellow]{e}[/yellow]")
            return

    if execute:
        console.print_json(json.dumps(res, default=str))
        return

    console.print(
        f"[bold]scalp plan[/bold] (DRY RUN) · equity ${res['equity']:,.0f} · "
        f"candidates {res['candidates']} · deploy ${res['deployed_usd']:,.0f}"
    )
    if not res["selected"]:
        console.print("[yellow]no scalp setups right now (score floor / ATR / fee-clearing not met)[/yellow]")
        return
    table = Table(title="crypto scalp — 1-min momentum (DRY RUN, no orders)")
    for col in ["#", "pair", "score", "notional", "rvol", "atr%", "tp/sl", "cost%", "breakeven wr"]:
        table.add_column(col, justify="left" if col == "pair" else "right")
    for i, p in enumerate(res["selected"], 1):
        e, s = p["exit"], p["signal"]
        table.add_row(
            str(i), p["ticker"], f"{p['setup_score']}", f"${p['notional']:,.0f}",
            f"{s['rvol']:.1f}", f"{s['atr_pct']:.2f}", f"+{e['tp_pct']:g}/-{e['sl_pct']:g}%",
            f"{e['cost_pct']:.2f}", f"{e['breakeven_wr'] * 100:.0f}%",
        )
    console.print(table)
    console.print(
        "[dim]net of ~0.5% fees + spread · spot long · 24/7 · "
        "`crypto-scalp --execute` to place PAPER orders[/dim]"
    )


@app.command("swing-bot-plan")
def swing_bot_plan_cmd() -> None:
    """Dry-run: build the swing-share plan (buys actual shares; no orders placed)."""
    from src.swing.runner import run

    with console.status("building swing-share plan (swing scan + sizing)..."):
        plan = run(execute=False)
    console.print(
        f"[bold]swing-share plan[/bold] · equity ${plan['equity']:,.0f} · "
        f"scanned {plan['scanned']} · candidates {plan['candidates']} · "
        f"deploy ${plan['deployed_usd']:,.0f}/${plan['deploy_cap_usd']:,.0f}"
    )
    if not plan["selected"]:
        console.print("[yellow]no qualifying swing setups (check min score / risk caps)[/yellow]")
        return
    table = Table(title="swing-share bot plan (DRY RUN, no orders)")
    for col in ["#", "ticker", "score", "notional", "risk $", "entry", "stop", "tp", "R:R", "stop %"]:
        table.add_column(col, justify="left" if col == "ticker" else "right")
    for i, p in enumerate(plan["selected"], 1):
        u, e = p["underlying"], p["exit"]
        table.add_row(
            str(i), p["ticker"], f"{p['setup_score']}", f"${p['notional']:,.0f}",
            f"${p['risk_usd']:,.0f}", f"${(u.get('entry') or 0):g}",
            f"${(u.get('stop') or 0):g}", f"${(u.get('tp') or 0):g}",
            f"{u.get('rr') or 0:.1f}", f"{e['sl_pct']:g}%",
        )
    console.print(table)
    console.print(
        "[dim]shares · risk = notional × stop% · regular hours · "
        "`swing-bot-run --execute` to place PAPER orders[/dim]"
    )


@app.command("swing-bot-run")
def swing_bot_run_cmd(
    execute: bool = typer.Option(False, "--execute", help="place PAPER share orders + manage exits (default: dry run)"),
) -> None:
    """Run one swing-share bot cycle. Default is a dry run; --execute places PAPER orders."""
    from src.bot.alpaca import AlpacaError
    from src.swing.runner import run

    if not execute:
        swing_bot_plan_cmd()
        return
    with console.status("running swing-share bot cycle (paper execute)..."):
        try:
            res = run(execute=True)
        except AlpacaError as e:
            console.print(f"[yellow]{e}[/yellow]")
            return
    console.print_json(json.dumps(res, default=str))


@app.command("graph-build")
def graph_build_cmd(
    seed_snapshots: bool = typer.Option(
        False, "--seed-snapshots", help="also seed from accrual snapshots (slower; needs aged data)"
    ),
) -> None:
    """Build the trade knowledge graph from logged trades → data/graph.json."""
    from src.config import DATA_DIR
    from src.graph.build import build
    from src.graph.insights import summary

    with console.status("building trade knowledge graph..."):
        g, counts = build(seed_snapshots=seed_snapshots)
        path = DATA_DIR / "graph.json"
        g.save(path)
    s = summary(g)
    console.print(
        f"[bold]knowledge graph[/bold] trades={s['n_trades']} "
        f"(bot={counts['bot_trades']}, snapshots={counts['snapshot_trades']}) · "
        f"nodes={s['n_nodes']} · edges={s['n_edges']}  →  {path}"
    )
    if s["n_trades"] == 0:
        console.print("[yellow]no completed trades yet — the graph fills in as the paper bot logs open+close trades.[/yellow]")
    elif s["underpowered"]:
        console.print(
            f"[yellow]underpowered: {s['n_trades']} trades — signal stats are noisy until "
            f"~{s['min_trades'] * 3}+; bot feedback stays gated/neutral.[/yellow]"
        )


@app.command("graph-insights")
def graph_insights_cmd(min_trades: int = 8) -> None:
    """What the graph has learned: signals + combos by realized expectancy (gated)."""
    from src.graph.build import build
    from src.graph.insights import rank_combos, rank_signals, summary

    g, _ = build()
    s = summary(g, min_trades=min_trades)
    console.print(
        f"[bold]graph insights[/bold] trades={s['n_trades']} · "
        f"actionable signals (≥{min_trades} trades)={s['signals_actionable']}"
    )
    if s["signals_actionable"] == 0:
        console.print("[yellow]nothing actionable yet — need more trades per signal; bot feedback is neutral until then.[/yellow]")
        return
    sig = rank_signals(g, min_trades=min_trades)
    t = Table(title="signals by realized expectancy (R)")
    for c in ["signal", "n", "win rate", "avg R"]:
        t.add_column(c, justify="left" if c == "signal" else "right")
    for r in sig["best"]:
        t.add_row(r["signal"], str(r["n"]), f"{r['win_rate']:.0%}", f"{r['avg_r']:+.2f}")
    console.print(t)
    combos = rank_combos(g, min_trades=min_trades)
    if combos:
        ct = Table(title="best signal combinations")
        for c in ["combo", "n", "win rate", "avg R"]:
            ct.add_column(c, justify="left" if c == "combo" else "right")
        for r in combos:
            ct.add_row(" + ".join(r["combo"]), str(r["n"]), f"{r['win_rate']:.0%}", f"{r['avg_r']:+.2f}")
        console.print(ct)


@app.command("warm")
def warm_cmd() -> None:
    """Pre-warm the scan caches so the web UI loads instantly. Wire to a cron.

    Warms the EXACT cache keys the frontend requests: the composite scan
    (limit=25, sort_by=composite) and the swing scan (limit=25). The dynamic
    universe is cached, so these keys stay stable between warms and the next
    page load is served from cache.
    """
    with console.status("warming scan caches..."):
        sq = scan(limit=25, sort_by="composite", force_refresh=True)
        sw = swing_scan(force_refresh=True, limit=25)
    console.print(
        f"[green]warmed[/green] scan({sq['scored']} scored) · "
        f"swing({sw['scored']} scored) @ {sq['as_of'][:19]}"
    )


@app.command()
def serve(port: int = 8000, reload: bool = True) -> None:
    """Start FastAPI server."""
    import uvicorn

    uvicorn.run("src.api:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    app()
