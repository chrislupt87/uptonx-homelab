#!/usr/bin/env bash
set -euo pipefail

# Full Swarm stack redeployment from scratch
#
# This script tears down all stacks and redeploys them in order.
# Run from the root of the uptonx-homelab repo, or set REPO_DIR.
#
# Prerequisites:
#   - Swarm has quorum (2+ managers healthy)
#   - SSH access to manager at .23
#   - /opt/secrets/swarm.env on manager (for Infisical)

MANAGER="root@192.168.1.23"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SWARM_DIR="$REPO_DIR/swarm"

echo "============================================"
echo " Full Swarm Stack Redeployment"
echo "============================================"
echo "  Manager:  $MANAGER"
echo "  Repo:     $REPO_DIR"
echo ""

# Step 1: Verify swarm health
echo "[1/6] Checking swarm health ..."
NODE_COUNT=$(ssh "$MANAGER" "docker node ls --format '{{.Status}}' | grep -c Ready")
echo "  $NODE_COUNT nodes Ready"
if [ "$NODE_COUNT" -lt 2 ]; then
  echo "WARNING: Less than 2 nodes Ready. Swarm may not have quorum."
  read -p "Continue anyway? (y/N) " -n 1 -r
  echo
  [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi

# Step 2: Remove existing stacks
echo "[2/6] Removing existing stacks ..."
EXISTING=$(ssh "$MANAGER" "docker stack ls --format '{{.Name}}'" 2>/dev/null || true)
for stack in $EXISTING; do
  echo "  Removing $stack ..."
  ssh "$MANAGER" "docker stack rm $stack" || true
done

if [ -n "$EXISTING" ]; then
  echo "  Waiting for cleanup ..."
  sleep 10
fi

# Step 3: Ensure overlay networks exist
echo "[3/6] Creating overlay networks ..."
ssh "$MANAGER" bash -s <<'NETEOF'
docker network ls --format '{{.Name}}' | grep -q '^proxy$'    || docker network create --driver overlay --attachable proxy
docker network ls --format '{{.Name}}' | grep -q '^internal$' || docker network create --driver overlay --attachable internal
echo "  Networks: proxy, internal"
NETEOF

# Step 4: Copy stack files to manager
echo "[4/6] Syncing stack files ..."
ssh "$MANAGER" "mkdir -p /opt/stacks"
rsync -az --delete \
  --exclude='.git' \
  --exclude='init-swarm.sh' \
  --exclude='deploy-all.sh' \
  --exclude='secrets/' \
  "$SWARM_DIR/" "$MANAGER:/opt/stacks/"

# Step 5: Deploy stacks in order
echo "[5/6] Deploying stacks ..."

STACKS=(portainer whoami landing uptime-kuma grafana cody)
for stack in "${STACKS[@]}"; do
  if [ -f "$SWARM_DIR/$stack/stack.yml" ]; then
    echo "  Deploying $stack ..."
    ssh "$MANAGER" "docker stack deploy -c /opt/stacks/$stack/stack.yml $stack"
    sleep 2
  else
    echo "  SKIPPING $stack (no stack.yml found)"
  fi
done

# Infisical (needs secrets)
if ssh "$MANAGER" "test -f /opt/secrets/swarm.env" 2>/dev/null; then
  echo "  Deploying infisical ..."
  ssh "$MANAGER" "set -a && source /opt/secrets/swarm.env && set +a && docker stack deploy -c /opt/stacks/infisical/stack.yml infisical"
else
  echo "  SKIPPING infisical — /opt/secrets/swarm.env not found"
fi

# Step 6: Verify
echo ""
echo "[6/6] Verification ..."
sleep 5
echo ""
echo "--- Stacks ---"
ssh "$MANAGER" "docker stack ls"
echo ""
echo "--- Services ---"
ssh "$MANAGER" "docker service ls"

echo ""
echo "============================================"
echo " Redeployment Complete"
echo "============================================"
echo ""
echo "  Portainer:  https://portainer.uptonx.com"
echo "  Whoami:     https://whoami.uptonx.com"
echo "  Landing:    https://uptonx.com"
echo "  Status:     https://status.uptonx.com"
echo "  Grafana:    https://grafana.uptonx.com"
echo "  Infisical:  https://infisical.uptonx.com"
echo ""
