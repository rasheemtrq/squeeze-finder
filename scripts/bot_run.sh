#!/usr/bin/env bash
#
# Auto-run the paper-trading bot. The bot self-gates on the Alpaca market clock,
# so this is safe to fire every 30 min — it no-ops instantly when the market is
# closed (weekends/overnight) and only opens/manages positions during RTH.
#
# Paper only (AlpacaClient refuses the live endpoint). Mac must be awake.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
cd /Users/rash/Documents/squeeze-finder

{
  echo "=== bot $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  /opt/homebrew/bin/uv run python -m src.cli bot-run --execute --limit 25
  echo "=== done $(date '+%H:%M:%S') ==="
} >> data/bot_run.log 2>&1
