#!/usr/bin/env bash
# Run on Aux 2 after context is set up.
# Initializes Docker Swarm, creates overlay networks, and labels the manager node.
set -euo pipefail

MANAGER_IP="192.168.1.80"

echo "==> Initializing Docker Swarm with advertise address ${MANAGER_IP}..."
docker swarm init --advertise-addr "${MANAGER_IP}" 2>/dev/null \
  || echo "Swarm already initialized, continuing..."

echo "==> Creating overlay network 'proxy' (10.10.0.0/24)..."
docker network create \
  --driver overlay \
  --subnet 10.10.0.0/24 \
  --attachable \
  proxy 2>/dev/null \
  || echo "Network 'proxy' already exists, continuing..."

echo "==> Creating overlay network 'internal' (backend-only)..."
docker network create \
  --driver overlay \
  --attachable \
  --internal \
  internal 2>/dev/null \
  || echo "Network 'internal' already exists, continuing..."

echo "==> Labeling manager node with role=manager..."
NODE_ID=$(docker info --format '{{.Swarm.NodeID}}')
docker node update --label-add role=manager "${NODE_ID}"

echo ""
echo "==> Swarm initialized. To get the worker join token, run:"
echo "    docker swarm join-token worker"
