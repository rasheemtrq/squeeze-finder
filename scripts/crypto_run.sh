#!/usr/bin/env bash
#
# Auto-run the spot-crypto paper-trading bot. Crypto trades 24/7, so unlike the
# options bot this has NO market-hours gate — every fire scans momentum, manages
# exits on open crypto positions, and opens new spot positions within the risk
# caps.
#
# Paper only (AlpacaClient refuses the live endpoint). Mac must be awake.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
cd /Users/rash/Documents/squeeze-finder

{
  echo "=== crypto-bot $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  /opt/homebrew/bin/uv run python -m src.cli crypto-run --execute --limit 15
  echo "=== done $(date '+%H:%M:%S') ==="
} >> data/crypto_run.log 2>&1
