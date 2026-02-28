#!/usr/bin/env bash
# Only run after init-context, init-swarm, init-storage, and init-secrets have all been completed.
# Deploys all stacks in dependency order.
set -euo pipefail

STACKS_DIR="/opt/stacks"

echo "==> Deploying Traefik (reverse proxy must be up first)..."
docker stack deploy -c "${STACKS_DIR}/traefik/stack.yml" traefik

echo "==> Waiting 10 seconds for Traefik to become ready..."
sleep 10

echo "==> Deploying Portainer..."
docker stack deploy -c "${STACKS_DIR}/portainer/stack.yml" portainer

echo "==> Deploying Technitium DNS..."
docker stack deploy -c "${STACKS_DIR}/technitium/stack.yml" technitium

echo "==> Deploying Vaultwarden..."
docker stack deploy -c "${STACKS_DIR}/vaultwarden/stack.yml" vaultwarden

echo "==> Deploying Uptime Kuma..."
docker stack deploy -c "${STACKS_DIR}/uptime-kuma/stack.yml" uptime-kuma

echo "==> Deploying Watchtower..."
docker stack deploy -c "${STACKS_DIR}/watchtower/stack.yml" watchtower

echo ""
echo "==> All stacks deployed. Check status with:"
echo "    docker stack ls"
echo "    docker service ls"
echo ""
echo "==> Service URLs:"
echo "    Traefik Dashboard : http://192.168.1.80:8080/dashboard/"
echo "    Portainer         : http://192.168.1.80:9000"
echo "    Technitium DNS UI : http://192.168.1.80:5380"
echo "    Vaultwarden       : http://192.168.1.80:8880"
echo "    Uptime Kuma       : http://192.168.1.80:3001"
