#!/usr/bin/env bash
set -euo pipefail

# Deploy all Swarm stacks to the multi-manager cluster
#
# Prerequisites:
#   - Swarm initialized (run init-swarm.sh first)
#   - Traefik running on CT 102 (.15) with Docker provider pointing at .23:2375
#   - SSH access to swarm manager as root

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
  "$SCRIPT_DIR/" "$MANAGER:/opt/stacks/"

# Deploy stacks
echo ""
echo "==> Deploying portainer ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/portainer/stack.yml portainer"

echo "==> Deploying whoami ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/whoami/stack.yml whoami"

echo "==> Deploying cody ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/cody/stack.yml cody"

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
echo " Post-deployment checklist:"
echo "========================================="
echo "1. Verify: curl -k https://whoami.uptonx.com"
echo "2. Set up Portainer admin: https://portainer.uptonx.com"
echo "3. Infisical: deploy manually once /opt/secrets/swarm.env is restored:"
echo "   ssh $MANAGER 'source /opt/secrets/swarm.env && docker stack deploy -c /opt/stacks/infisical/stack.yml infisical'"
echo ""
