#!/usr/bin/env bash
#
# Auto-run the swing-SHARE bot (the stock strategy). Self-gates on the Alpaca
# market clock, so it's safe to fire every 30 min — it no-ops when the market is
# closed and only buys/manages shares during regular hours. Multi-week holds.
#
# Paper only (AlpacaClient refuses the live endpoint). Mac must be awake.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
cd /Users/rash/Documents/squeeze-finder

{
  echo "=== swing-bot $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  /opt/homebrew/bin/uv run python -m src.cli swing-bot-run --execute
  echo "=== done $(date '+%H:%M:%S') ==="
} >> data/swing_run.log 2>&1
