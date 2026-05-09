#!/usr/bin/env bash
# One-shot bootstrap for the VibeFM Hetzner box.
# Run as root on a fresh Debian/Ubuntu box: `bash setup.sh`
# Idempotent — safe to re-run.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/zertyn-ai/personalized-radio-station.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="/opt/vibefm"
STATE_DIR="/var/lib/vibefm"
SERVICE_USER="vibefm"
DEPLOY_DIR="${INSTALL_DIR}/deploy"

if [[ $EUID -ne 0 ]]; then
	echo "Run as root." >&2
	exit 1
fi

echo "[1/7] apt deps"
apt-get update -y
apt-get install -y --no-install-recommends \
	git ffmpeg ca-certificates curl debian-keyring debian-archive-keyring apt-transport-https

echo "[2/7] Caddy (skip if already installed)"
if ! command -v caddy >/dev/null 2>&1; then
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
		| gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
		> /etc/apt/sources.list.d/caddy-stable.list
	apt-get update -y
	apt-get install -y caddy
fi

echo "[3/7] uv + node + pnpm (skip if already installed)"
if ! command -v uv >/dev/null 2>&1; then
	curl -LsSf https://astral.sh/uv/install.sh | sh
	install -m 0755 /root/.local/bin/uv /usr/local/bin/uv
fi
if ! command -v node >/dev/null 2>&1; then
	curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
	apt-get install -y nodejs
fi
if ! command -v pnpm >/dev/null 2>&1; then
	npm install -g pnpm
fi

echo "[4/7] service user + dirs"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$STATE_DIR/episodes"
chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR"

echo "[5/7] clone or update repo (branch: $BRANCH)"
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
	git clone "$REPO_URL" "$INSTALL_DIR"
fi
git -C "$INSTALL_DIR" fetch --depth=1 origin "$BRANCH"
git -C "$INSTALL_DIR" checkout "$BRANCH"
git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "[6/7] install python deps + build frontend"
sudo -u "$SERVICE_USER" -H bash -lc "cd $INSTALL_DIR/backend && /usr/local/bin/uv sync"
sudo -u "$SERVICE_USER" -H bash -lc "cd $INSTALL_DIR && pnpm install --frozen-lockfile && pnpm build:frontend"

echo "[7/7] install systemd unit"
install -m 0644 "$DEPLOY_DIR/vibefm.service" /etc/systemd/system/vibefm.service
systemctl daemon-reload
systemctl enable --now vibefm.service

echo
echo "Done. Status:"
systemctl --no-pager status vibefm.service | head -5
echo
echo "NOTE: Caddyfile NOT installed automatically (box may host other sites)."
echo "Append this block to /etc/caddy/Caddyfile, then 'systemctl reload caddy':"
echo "----"
cat "$DEPLOY_DIR/Caddyfile"
echo "----"
echo "Logs:  journalctl -u vibefm -f"
