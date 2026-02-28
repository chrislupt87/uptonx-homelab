#!/usr/bin/env bash
# Run after init-swarm.sh has been executed on the manager.
#
# To get the real join token, run on the manager (or via aux2 context):
#   docker swarm join-token worker
#
# Then replace the placeholder below with the actual token.
set -euo pipefail

# ┌─────────────────────────────────────────────────────┐
# │  REPLACE THIS with the real token from:             │
# │  docker swarm join-token worker                     │
# └─────────────────────────────────────────────────────┘
JOIN_TOKEN="SWMTKN-CHANGEME-paste-real-token-here"
MANAGER_ADDR="192.168.1.80:2377"

# Worker nodes
declare -A WORKERS=(
  ["Aux"]="192.168.1.18"
  ["MSI"]="192.168.1.74"
  ["Control"]="192.168.1.77"
  ["AI Node"]="192.168.1.69"
)

echo "==> Joining worker nodes to the swarm..."
echo "    Manager: ${MANAGER_ADDR}"
echo ""

for NAME in "${!WORKERS[@]}"; do
  IP="${WORKERS[$NAME]}"
  echo "==> Joining ${NAME} (${IP})..."
  ssh "root@${IP}" "docker swarm join --token ${JOIN_TOKEN} ${MANAGER_ADDR}" 2>&1 \
    || echo "    ${NAME} may already be in the swarm or SSH failed — check manually."
  echo ""
done

echo "==> Done. Verify all nodes with:"
echo "    docker node ls"
