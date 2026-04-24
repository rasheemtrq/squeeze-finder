# Deploy

Split architecture: **Vercel** hosts the Next.js frontend, **Vultr** hosts the FastAPI backend. Free tier on Vercel, ~$6/mo on Vultr, ~$10/yr for a domain.

```
user browser  ──HTTPS──>  Vercel (squeeze-finder.vercel.app)
                              └──HTTPS──>  Vultr  (squeeze.yourdomain.com)
                                                  ├─ nginx :443 (TLS)
                                                  └─ FastAPI :8100 (systemd)
```

---

## Part 1 — Vultr backend (10 minutes)

### Prereqs
- Ubuntu 22.04/24.04 or Debian 12 VPS (any other distro works with tweaks)
- Root SSH access via **key-based auth** (disable password auth — see Hardening below)
- A subdomain pointed at the server's public IP via DNS A record. Propagation takes 1–10 min.

### Step 1 — SSH in and fetch the installer

```bash
ssh root@YOUR_SERVER_IP

# Option A: private repo — clone with a Personal Access Token first
#   (settings → developer settings → tokens classic, repo scope, 90d expiry)
git clone https://<PAT>@github.com/rasheemtrq/squeeze-finder.git /opt/squeeze-finder
bash /opt/squeeze-finder/deploy/install.sh

# Option B: public repo one-liner
curl -fsSL https://raw.githubusercontent.com/rasheemtrq/squeeze-finder/main/deploy/install.sh | bash
```

### Step 2 — Answer the 5 prompts

The installer asks for:

| Prompt | Example |
|---|---|
| Subdomain | `squeeze.yourdomain.com` |
| Email (LetsEncrypt) | `you@you.com` |
| Vercel URL | `https://squeeze-finder.vercel.app` (or `skip` for now) |
| FINNHUB_API_KEY | freshly rotated Finnhub key |
| OPENROUTER_API_KEY | freshly rotated OpenRouter key |

Then it will:
1. Install system deps (`git`, `nginx`, `python3-venv`, `build-essential`)
2. Install `uv` package manager
3. Create `squeeze` system user
4. Clone the repo to `/opt/squeeze-finder`
5. Build venv + install Python deps
6. Template `.env` with your keys
7. Drop systemd unit (`squeeze-finder.service`)
8. Write nginx server block at `/etc/nginx/sites-available/squeeze-finder`
9. Run `certbot --nginx` to issue a LetsEncrypt TLS cert
10. Start the service and run a health check

### Step 3 — Verify

```bash
# running service
sudo systemctl status squeeze-finder --no-pager

# live logs
sudo journalctl -u squeeze-finder -f

# public health check
curl -s https://squeeze.yourdomain.com/api/health | jq
#   { "ok": true, "universe": 47, "cors_origins": [...] }

# interactive docs
open https://squeeze.yourdomain.com/docs
```

---

## Part 2 — Vercel frontend (5 minutes)

### Step 1 — Import the repo

1. Go to https://vercel.com/new
2. **Add GitHub account** (if first time) → grant access to `rasheemtrq/squeeze-finder`
3. Click **Import** next to `squeeze-finder`
4. **Root Directory**: `web`   ← critical, don't leave as `.`
5. Framework preset: Next.js (auto-detected)

### Step 2 — Environment variables (before first deploy)

Under *Environment Variables*, add:

| Key | Value | Environments |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://squeeze.yourdomain.com` | Production, Preview, Development |

### Step 3 — Deploy

Click **Deploy**. ~2 min for first build. You'll get a `*.vercel.app` URL.

### Step 4 — Update backend CORS

Add the Vercel URL to the backend's allowed origins:

```bash
ssh root@YOUR_SERVER_IP
sudo -e /opt/squeeze-finder/.env
# edit CORS_ORIGINS to include https://squeeze-finder.vercel.app
sudo systemctl restart squeeze-finder
```

Then reload the frontend — the scan table should populate.

---

## Part 3 — Redeploying

### Backend (after pushing to `main`)

```bash
ssh root@YOUR_SERVER_IP
sudo bash /opt/squeeze-finder/deploy/update.sh
```

This pulls, reinstalls deps only if `pyproject.toml` changed, restarts the service, runs a health check.

### Frontend

Just `git push`. Vercel auto-deploys every push to `main`, with preview URLs for branches/PRs.

---

## Hardening (do this even for a hobby project)

Vultr's default image has root password login enabled. Before anything else:

```bash
# 1. set up an SSH key from your Mac if you haven't
ssh-keygen -t ed25519                                      # on your Mac
ssh-copy-id root@YOUR_SERVER_IP                            # on your Mac

# 2. on the server: disable password auth
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 3. enable basic firewall (only 22/80/443)
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

# 4. unattended security upgrades
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## Running alongside another app on the same server

Designed to coexist:

| Resource | What we use |
|---|---|
| Internal port | `127.0.0.1:8100` — not publicly exposed; unlikely collision |
| nginx | Adds a new server block keyed on your subdomain; doesn't touch existing sites |
| systemd | Unit named `squeeze-finder.service` |
| User | System user `squeeze` (no shell, no sudo) |
| Data | `/opt/squeeze-finder/data/` |

Caveats:
- If your other app uses **Caddy** (not nginx): the installer detects this and drops a `Caddyfile.snippet` at `/etc/caddy/conf.d/squeeze-finder.caddy`. Make sure your main Caddyfile imports `conf.d/*.caddy`, then `caddy reload`.
- If your other app uses ports 80/443 without a reverse proxy in front, you have a conflict. Put nginx or Caddy in front of it first.
- Low-spec servers (< 1 GB RAM): disable prewarm in `.env` (`SQUEEZE_PREWARM=0`) so startup doesn't thrash.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `certbot` fails with "DNS problem" | DNS hasn't propagated. Wait 5 min, verify with `dig squeeze.yourdomain.com`, re-run `sudo certbot --nginx -d squeeze.yourdomain.com` |
| 502 Bad Gateway | Service not running. `sudo systemctl status squeeze-finder` + `journalctl -u squeeze-finder -n 50` |
| `/api/scan` returns 403 CORS on Vercel | `.env` `CORS_ORIGINS` missing the Vercel URL. Edit `.env`, restart service |
| Cold scan times out at nginx | Increase `proxy_read_timeout` in `/etc/nginx/sites-available/squeeze-finder`. Default is 180s |
| `uv: command not found` after reboot | Login shell doesn't have `/usr/local/bin` in PATH. `export PATH="/usr/local/bin:$PATH"` or re-source profile |
| Wrong Python version | `uv venv --python 3.11 --clear` then re-install. uv downloads 3.11 if missing |
| Apewisdom rate-limited | 15min cache TTL should prevent this. If it happens, bump `CACHE_TTL_SECONDS` in `src/data/apewisdom.py` |

Check service health any time:

```bash
curl -s https://squeeze.yourdomain.com/api/health | jq
journalctl -u squeeze-finder --since "10 min ago" --no-pager
sudo systemctl status squeeze-finder --no-pager
```
