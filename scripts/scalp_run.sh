#!/usr/bin/env bash
#
# Auto-run the intraday crypto SCALP bot, every ~60s (launchd StartInterval 60).
# Each cycle pulls live 1-min bars, manages open scalp exits (TP/SL/time on the
# gross move), and opens new scalps within the risk caps. 24/7, no market gate.
#
# Paper only (AlpacaClient refuses live). Mac must be awake. Outcomes are logged
# net of fees+spread to data/bot_trades.jsonl.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
cd /Users/rash/Documents/squeeze-finder

{
  echo "=== scalp $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  /opt/homebrew/bin/uv run python -m src.cli crypto-scalp --execute
  echo "=== done $(date '+%H:%M:%S') ==="
} >> data/scalp_run.log 2>&1
