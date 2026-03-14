#!/usr/bin/env bash
set -euo pipefail

# Rejoin a Proxmox host as a Docker Swarm worker after rebuild
#
# Usage: ./rejoin-swarm-worker.sh <worker-ip>
# Example: ./rejoin-swarm-worker.sh 192.168.1.74
#
# Prerequisites:
#   - Docker installed on the worker host
#   - SSH access to both worker and a swarm manager
#   - Swarm manager at .23 is healthy

WORKER_IP="${1:?Usage: $0 <worker-ip>}"
MANAGER="root@192.168.1.23"

echo "============================================"
echo " Rejoin Swarm Worker: $WORKER_IP"
echo "============================================"

# Determine SSH user based on host
case "$WORKER_IP" in
  192.168.1.95) WORKER_SSH="chris@$WORKER_IP" ;;
  *)            WORKER_SSH="root@$WORKER_IP" ;;
esac

# Step 1: Verify Docker is running on worker
echo ""
echo "[1/5] Checking Docker on worker ..."
ssh "$WORKER_SSH" "docker info --format '{{.ServerVersion}}'" || {
  echo "ERROR: Docker not running on $WORKER_IP"
  echo "Install Docker first: curl -fsSL https://get.docker.com | sh"
  exit 1
}

# Step 2: Leave any stale swarm
echo "[2/5] Leaving stale swarm (if any) ..."
ssh "$WORKER_SSH" "docker swarm leave --force 2>/dev/null || true"

# Step 3: Get worker join token from manager
echo "[3/5] Getting worker join token from manager ..."
WORKER_TOKEN=$(ssh "$MANAGER" "docker swarm join-token -q worker")
echo "  Token: ${WORKER_TOKEN:0:12}..."

# Step 4: Join swarm
echo "[4/5] Joining swarm ..."
if [ "$WORKER_IP" = "192.168.1.95" ]; then
  ssh "$WORKER_SSH" "sudo docker swarm join --token $WORKER_TOKEN 192.168.1.23:2377"
else
  ssh "$WORKER_SSH" "docker swarm join --token $WORKER_TOKEN 192.168.1.23:2377"
fi

# Step 5: Apply node labels
echo "[5/5] Applying node labels ..."
HOSTNAME=$(ssh "$WORKER_SSH" "hostname")
case "$WORKER_IP" in
  192.168.1.74) ssh "$MANAGER" "docker node update --label-add host=msi $HOSTNAME" ;;
  192.168.1.69) ssh "$MANAGER" "docker node update --label-add host=ai $HOSTNAME" ;;
  192.168.1.95) ssh "$MANAGER" "docker node update --label-add host=workstation --label-add gpu=true $HOSTNAME" ;;
esac

echo ""
echo "============================================"
echo " Done! Verify with:"
echo "   ssh $MANAGER docker node ls"
echo "============================================"
