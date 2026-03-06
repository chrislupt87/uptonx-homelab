#!/usr/bin/env bash
set -euo pipefail

# Deploy all Swarm stacks
# Prerequisites:
#   - Swarm initialized (run init-swarm.sh first)
#   - /opt/secrets/swarm.env exists on the manager with required vars
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

# Check secrets env file
echo "==> Checking secrets ..."
REQUIRED_VARS="INFISICAL_ENCRYPTION_KEY INFISICAL_AUTH_SECRET INFISICAL_POSTGRES_PASSWORD"
ssh "$MANAGER" bash -s <<CHECKEOF
set -euo pipefail
if [ ! -f /opt/secrets/swarm.env ]; then
  echo "ERROR: /opt/secrets/swarm.env not found."
  echo "Create it with:"
  echo "  INFISICAL_ENCRYPTION_KEY=..."
  echo "  INFISICAL_AUTH_SECRET=..."
  echo "  INFISICAL_POSTGRES_PASSWORD=..."
  exit 1
fi
source /opt/secrets/swarm.env
for var in $REQUIRED_VARS; do
  if [ -z "\${!var:-}" ]; then
    echo "ERROR: \$var is not set in /opt/secrets/swarm.env"
    exit 1
  fi
done
echo "All required secrets present."
CHECKEOF

# Deploy stacks
echo ""
echo "==> Deploying portainer ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/portainer/stack.yml portainer"

echo "==> Deploying gitea ..."
ssh "$MANAGER" "docker stack deploy -c /opt/stacks/gitea/stack.yml gitea"

echo "==> Deploying infisical ..."
ssh "$MANAGER" "source /opt/secrets/swarm.env && docker stack deploy -c /opt/stacks/infisical/stack.yml infisical"

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
echo "3. Verify Gitea: https://gitea.uptonx.com"
echo "4. Verify Infisical: https://infisical.uptonx.com"
echo ""
