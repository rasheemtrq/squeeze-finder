#!/usr/bin/env bash
#
# Pull latest, rebuild venv if deps changed, restart the service.
# Idempotent. Run as root.
#
#   sudo bash /opt/squeeze-finder/deploy/update.sh

set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "run as root (sudo bash $0)" >&2
    exit 1
fi

INSTALL_DIR="/opt/squeeze-finder"
SERVICE_USER="squeeze"

log() { echo -e "\033[1;36m[squeeze-finder]\033[0m $*"; }

cd "$INSTALL_DIR"

# All git operations run as the repo owner ($SERVICE_USER) to avoid
# git's "dubious ownership" safe.directory check when invoked as root.
as_user() { sudo -u "$SERVICE_USER" "$@"; }

OLD_HEAD=$(as_user git rev-parse HEAD)
log "pulling"
as_user git pull --ff-only
NEW_HEAD=$(as_user git rev-parse HEAD)

if [[ "$OLD_HEAD" == "$NEW_HEAD" ]]; then
    log "already at $NEW_HEAD — restarting service only"
else
    log "updated $OLD_HEAD → $NEW_HEAD"
    if as_user git diff --name-only "$OLD_HEAD" "$NEW_HEAD" | grep -qE '^(pyproject\.toml|uv\.lock)$'; then
        log "dependency change detected — reinstalling"
        as_user /usr/local/bin/uv pip install -e .
    fi
fi

log "restarting squeeze-finder"
systemctl restart squeeze-finder
sleep 2
systemctl status squeeze-finder --no-pager | head -10
log "health check:"
curl -sf http://127.0.0.1:8100/api/health || echo "  (health check failed — see logs: journalctl -u squeeze-finder -n 50)"
