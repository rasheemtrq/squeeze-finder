#!/usr/bin/env bash
#
# Daily swing-snapshot accrual — the fidelity engine.
#
# Records one forward-return snapshot per scored name to data/screens/swing_*.jsonl.
# `swing-backtest` reads these once picks age past the hold window and reports
# realized expectancy. This accrual is the ONLY thing that makes the scanner
# high-fidelity: free data sources have no history to backtest these signals
# against, so the dataset must be built forward, one market day at a time.
#
# Wire to cron (weekdays, after the US close). macOS note: /usr/sbin/cron needs
# Full Disk Access (System Settings > Privacy) and the Mac must be awake.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
cd /Users/rash/Documents/squeeze-finder

{
  echo "=== accrual $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  /opt/homebrew/bin/uv run python -m src.cli accrue
  echo "=== done $(date '+%H:%M:%S') ==="
} >> data/accrual.log 2>&1
