#!/usr/bin/env bash
set -euo pipefail

# Deploy all Swarm stacks to the multi-manager cluster
#
# Prerequisites:
#   - Swarm initialized (run init-swarm.sh first)
#   - Traefik running on CT 102 (.15) with Docker provider pointing at .23:2375
#   - SSH access to swarm manager as root
#   - /opt/secrets/swarm.env on manager (for Infisical)

MANAGER="root@192.168.1.23"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================="
echo " Deploying Swarm Stacks"
echo "========================================="

# Copy stack files to manager
echo "==> Copying stack files to manager ..."
ssh "$MANAGER" "mkdir -p /opt/stacks"
rsync -az --delete \
  --exclude='.git' \
  --exclude='init-swarm.sh' \
  --exclude='deploy-all.sh' \
  --exclude='secrets/' \
  "$SCRIPT_DIR/" "$MANAGER:/opt/stacks/"

# Core stacks
echo ""
echo "==> Deploying portainer ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/portainer/stack.yml portainer"

echo "==> Deploying whoami ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/whoami/stack.yml whoami"

echo "==> Deploying cody ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/cody/stack.yml cody"

echo "==> Deploying landing ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/landing/stack.yml landing"

# Monitoring
echo "==> Deploying uptime-kuma ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/uptime-kuma/stack.yml uptime-kuma"

echo "==> Deploying grafana ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/grafana/stack.yml grafana"

# Infisical (needs secrets)
if ssh "$MANAGER" "test -f /opt/secrets/swarm.env" 2>/dev/null; then
  echo "==> Deploying infisical (secrets found) ..."
  ssh "$MANAGER" "set -a && source /opt/secrets/swarm.env && set +a && docker stack deploy -c /opt/stacks/infisical/stack.yml infisical"
else
  echo "==> SKIPPING infisical — /opt/secrets/swarm.env not found"
  echo "    Run: swarm/secrets/load-secrets.sh after creating the env file"
fi

# Verify
echo ""
echo "========================================="
echo " Verification"
echo "========================================="
ssh "$MANAGER" "docker stack ls"
echo ""
ssh "$MANAGER" "docker service ls"

echo ""
echo "========================================="
echo " Services"
echo "========================================="
echo "  whoami:     https://whoami.uptonx.com"
echo "  portainer:  https://portainer.uptonx.com"
echo "  cody:       https://cody.uptonx.com"
echo "  landing:    https://uptonx.com"
echo "  status:     https://status.uptonx.com"
echo "  grafana:    https://grafana.uptonx.com"
echo "  infisical:  https://infisical.uptonx.com"
echo ""
