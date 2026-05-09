#!/usr/bin/env bash
# Run from your laptop. Pulls latest on the box and restarts the service.
# Assumes ~/.ssh/config has a `zertyn-lab` host alias.
# Override branch with: BRANCH=feat/foo ./deploy.sh

set -euo pipefail

SSH_HOST="${SSH_HOST:-zertyn-lab}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="/opt/vibefm"

ssh "$SSH_HOST" bash -s "$BRANCH" <<'EOF'
set -euo pipefail
BRANCH="$1"
INSTALL_DIR="/opt/vibefm"

sudo -u vibefm bash -lc "cd $INSTALL_DIR && git fetch --depth=1 origin $BRANCH && git checkout $BRANCH && git reset --hard origin/$BRANCH"
sudo -u vibefm bash -lc "cd $INSTALL_DIR/backend && /usr/local/bin/uv sync"
sudo systemctl restart vibefm
sleep 1
sudo systemctl --no-pager status vibefm | head -8
EOF
