#!/usr/bin/env bash
#
# squeeze-finder one-shot installer for Ubuntu/Debian Vultr VPS.
#
# Interactive. Idempotent. Safe to re-run. Does NOT touch your existing sites.
#
# Quick start (on the server, as root):
#   curl -fsSL https://raw.githubusercontent.com/rasheemtrq/squeeze-finder/main/deploy/install.sh | bash
#
# Or clone + run:
#   git clone https://github.com/rasheemtrq/squeeze-finder.git /opt/squeeze-finder
#   sudo bash /opt/squeeze-finder/deploy/install.sh
#
# If the repo is private, clone first with a PAT (easier than installer-side auth).

set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "run as root (sudo bash $0)" >&2
    exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/rasheemtrq/squeeze-finder.git}"
INSTALL_DIR="/opt/squeeze-finder"
SERVICE_USER="squeeze"
INTERNAL_PORT=8100

ink_cyan()  { printf "\033[1;36m%s\033[0m\n" "$*"; }
ink_green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
ink_yellow(){ printf "\033[1;33m%s\033[0m\n" "$*"; }
ink_red()   { printf "\033[1;31m%s\033[0m\n" "$*"; }
log() { ink_cyan "[squeeze-finder] $*"; }
bad() { ink_red "[squeeze-finder] $*" >&2; }

# ────────────────────────────────────────────────────────────────────────
#  collect inputs up-front
# ────────────────────────────────────────────────────────────────────────
ink_cyan "━━ squeeze-finder installer ━━"
echo

prompt() {
    local var_name="$1" label="$2" default="${3:-}" secret="${4:-}"
    local value=""
    while [[ -z "$value" ]]; do
        if [[ -n "$default" ]]; then
            read -rp "$label [$default]: " value || true
            value="${value:-$default}"
        else
            if [[ "$secret" == "secret" ]]; then
                read -rsp "$label: " value; echo
            else
                read -rp "$label: " value
            fi
        fi
    done
    printf -v "$var_name" '%s' "$value"
}

prompt DOMAIN "Subdomain for the backend (e.g. squeeze.yourdomain.com)"
prompt LE_EMAIL "Email for Let's Encrypt cert recovery notifications"
prompt VERCEL_URL "Vercel frontend URL (e.g. https://squeeze-finder.vercel.app). Use 'skip' if not deployed yet" "skip"
prompt FINNHUB_KEY "FINNHUB_API_KEY" "" secret
prompt OPENROUTER_KEY "OPENROUTER_API_KEY" "" secret

echo
log "summary:"
echo "  domain:       $DOMAIN"
echo "  le email:     $LE_EMAIL"
echo "  vercel url:   $VERCEL_URL"
echo "  install dir:  $INSTALL_DIR"
echo "  service user: $SERVICE_USER"
echo "  internal port: $INTERNAL_PORT"
echo
read -rp "proceed? [Y/n] " yn
[[ "${yn:-y}" =~ ^[Yy]$ ]] || { ink_yellow "aborted."; exit 0; }

# ────────────────────────────────────────────────────────────────────────
#  detect reverse proxy (nginx vs caddy vs none)
# ────────────────────────────────────────────────────────────────────────
PROXY=""
if systemctl is-active --quiet caddy 2>/dev/null; then
    PROXY="caddy"
    log "detected active Caddy — will install as Caddyfile snippet (you reload manually)"
elif systemctl is-active --quiet nginx 2>/dev/null || command -v nginx >/dev/null 2>&1; then
    PROXY="nginx"
    log "detected nginx — will install an nginx server block + run certbot"
else
    PROXY="nginx"
    log "no reverse proxy detected — will install nginx"
fi

# ────────────────────────────────────────────────────────────────────────
#  1. system packages
# ────────────────────────────────────────────────────────────────────────
log "installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

PKGS=(git curl ca-certificates python3 python3-venv python3-dev
      build-essential pkg-config libffi-dev libssl-dev)
if [[ "$PROXY" == "nginx" ]]; then
    PKGS+=(nginx certbot python3-certbot-nginx)
fi
apt-get install -y --no-install-recommends "${PKGS[@]}"

# ────────────────────────────────────────────────────────────────────────
#  2. uv
# ────────────────────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
    log "installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

# ────────────────────────────────────────────────────────────────────────
#  3. service user
# ────────────────────────────────────────────────────────────────────────
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    log "creating '$SERVICE_USER' system user"
    useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# ────────────────────────────────────────────────────────────────────────
#  4. clone / pull + venv
# ────────────────────────────────────────────────────────────────────────
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    log "cloning $REPO_URL → $INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
else
    log "pulling latest on $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
fi

log "building venv + installing deps (~60s first run)"
cd "$INSTALL_DIR"
/usr/local/bin/uv venv --python 3.11 --clear
/usr/local/bin/uv pip install -e . --quiet

mkdir -p "$INSTALL_DIR/data/cache" "$INSTALL_DIR/data/deepdives" "$INSTALL_DIR/data/screens"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ────────────────────────────────────────────────────────────────────────
#  5. .env
# ────────────────────────────────────────────────────────────────────────
log "writing /opt/squeeze-finder/.env"
CORS_VALUE="http://localhost:3000,http://127.0.0.1:3000"
if [[ "$VERCEL_URL" != "skip" ]]; then
    CORS_VALUE="${VERCEL_URL%/},${CORS_VALUE}"
fi

cat > "$INSTALL_DIR/.env" <<EOF
FINNHUB_API_KEY=$FINNHUB_KEY
OPENROUTER_API_KEY=$OPENROUTER_KEY
SEC_USER_AGENT=squeeze-finder $LE_EMAIL
CORS_ORIGINS=$CORS_VALUE
SQUEEZE_PREWARM=1
EOF
chmod 600 "$INSTALL_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"

# ────────────────────────────────────────────────────────────────────────
#  6. systemd unit
# ────────────────────────────────────────────────────────────────────────
log "installing systemd unit"
install -m 0644 "$INSTALL_DIR/deploy/squeeze-finder.service" /etc/systemd/system/squeeze-finder.service
systemctl daemon-reload
systemctl enable squeeze-finder.service >/dev/null 2>&1 || true

# ────────────────────────────────────────────────────────────────────────
#  7. reverse proxy
# ────────────────────────────────────────────────────────────────────────
if [[ "$PROXY" == "nginx" ]]; then
    log "installing nginx site for $DOMAIN"
    sed "s/SQUEEZE_HOST/$DOMAIN/g" "$INSTALL_DIR/deploy/squeeze-finder.nginx.conf" \
        > /etc/nginx/sites-available/squeeze-finder
    ln -sf /etc/nginx/sites-available/squeeze-finder /etc/nginx/sites-enabled/squeeze-finder
    nginx -t
    systemctl reload nginx

    log "requesting TLS cert from Let's Encrypt (requires DNS A record to be live)"
    if certbot --nginx \
        -d "$DOMAIN" \
        --non-interactive --agree-tos --email "$LE_EMAIL" \
        --redirect; then
        ink_green "  TLS cert installed"
    else
        ink_yellow "  certbot failed — check DNS A record points at this server, then run:"
        echo "    sudo certbot --nginx -d $DOMAIN"
    fi
else
    # Caddy path — write snippet, user reloads
    CADDY_DROPIN="/etc/caddy/conf.d/squeeze-finder.caddy"
    mkdir -p /etc/caddy/conf.d
    sed "s/SQUEEZE_HOST/$DOMAIN/g" "$INSTALL_DIR/deploy/Caddyfile.snippet" > "$CADDY_DROPIN"
    ink_yellow "caddy snippet written to $CADDY_DROPIN"
    ink_yellow "make sure your main Caddyfile imports conf.d/*.caddy, then:"
    echo "  sudo caddy reload --config /etc/caddy/Caddyfile"
fi

# ────────────────────────────────────────────────────────────────────────
#  8. start service
# ────────────────────────────────────────────────────────────────────────
log "starting squeeze-finder service"
systemctl restart squeeze-finder
sleep 3

if systemctl is-active --quiet squeeze-finder; then
    ink_green "  service running"
else
    bad "  service failed to start — check: journalctl -u squeeze-finder -n 50 --no-pager"
    exit 1
fi

log "health check (internal):"
if curl -sf "http://127.0.0.1:$INTERNAL_PORT/api/health" > /tmp/health.json; then
    cat /tmp/health.json && echo
else
    bad "  local health check failed"
fi

if [[ "$PROXY" == "nginx" ]]; then
    log "health check (public HTTPS):"
    sleep 2
    curl -sf "https://$DOMAIN/api/health" > /tmp/health-https.json 2>/dev/null \
        && { cat /tmp/health-https.json && echo; } \
        || ink_yellow "  https check failed — DNS may not be propagated yet"
fi

cat <<EOF

$(ink_green "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
$(ink_green " ✅ squeeze-finder is live")
$(ink_green "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

  API:          https://$DOMAIN/api/health
  Docs:         https://$DOMAIN/docs
  Logs:         journalctl -u squeeze-finder -f
  Update:       sudo bash $INSTALL_DIR/deploy/update.sh
  Restart:      sudo systemctl restart squeeze-finder
  Edit env:     sudo -e $INSTALL_DIR/.env

  Vercel frontend: set these env vars in the Vercel dashboard:
    NEXT_PUBLIC_API_BASE = https://$DOMAIN

  First scan prewarms in background (~45s). Hit the health endpoint to
  confirm responsive; first /api/scan will return cached data shortly after.
EOF
