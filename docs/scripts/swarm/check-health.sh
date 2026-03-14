#!/usr/bin/env bash
set -euo pipefail

# Swarm Health Check — prints status table for all services and nodes
#
# Usage: ./check-health.sh
# Requires SSH access to manager at .23

MANAGER="root@192.168.1.23"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo "============================================"
echo " UptonX Swarm Health Check"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

# --- Node Status ---
echo ""
echo -e "${CYAN}=== SWARM NODES ===${NC}"
printf "%-25s %-10s %-12s %-10s\n" "HOSTNAME" "STATUS" "ROLE" "MANAGER"
printf "%-25s %-10s %-12s %-10s\n" "--------" "------" "----" "-------"

ssh "$MANAGER" "docker node ls --format '{{.Hostname}}\t{{.Status}}\t{{.ManagerStatus}}\t{{.Availability}}'" | \
while IFS=$'\t' read -r hostname status mgr_status avail; do
  role="worker"
  if [ -n "$mgr_status" ]; then
    role="manager"
  fi

  if [ "$status" = "Ready" ] && [ "$avail" = "Active" ]; then
    status_icon="${GREEN}✓ Ready${NC}"
  else
    status_icon="${RED}✗ $status/$avail${NC}"
  fi

  printf "%-25s %-22b %-12s %-10s\n" "$hostname" "$status_icon" "$role" "${mgr_status:-—}"
done

# --- Stack Status ---
echo ""
echo -e "${CYAN}=== STACKS ===${NC}"
ssh "$MANAGER" "docker stack ls"

# --- Service Status ---
echo ""
echo -e "${CYAN}=== SERVICES ===${NC}"
printf "%-35s %-12s %-8s\n" "SERVICE" "REPLICAS" "STATUS"
printf "%-35s %-12s %-8s\n" "-------" "--------" "------"

ssh "$MANAGER" "docker service ls --format '{{.Name}}\t{{.Replicas}}\t{{.Image}}'" | \
while IFS=$'\t' read -r name replicas image; do
  current=$(echo "$replicas" | cut -d/ -f1)
  desired=$(echo "$replicas" | cut -d/ -f2)

  if [ "$current" = "$desired" ] && [ "$current" != "0" ]; then
    status="${GREEN}✓ OK${NC}"
  elif [ "$current" = "0" ]; then
    status="${RED}✗ DOWN${NC}"
  else
    status="${YELLOW}⚠ PARTIAL${NC}"
  fi

  printf "%-35s %-12s %-20b\n" "$name" "$replicas" "$status"
done

# --- Overlay Networks ---
echo ""
echo -e "${CYAN}=== OVERLAY NETWORKS ===${NC}"
ssh "$MANAGER" "docker network ls --filter driver=overlay --format '{{.Name}}\t{{.Scope}}\t{{.Driver}}'"

# --- Standalone Services (ping check) ---
echo ""
echo -e "${CYAN}=== STANDALONE SERVICES ===${NC}"
printf "%-25s %-18s %-10s\n" "SERVICE" "ADDRESS" "STATUS"
printf "%-25s %-18s %-10s\n" "-------" "-------" "------"

declare -A STANDALONE=(
  ["Traefik"]="192.168.1.15:443"
  ["Technitium DNS"]="192.168.1.51:5380"
  ["Frigate NVR"]="192.168.1.18:5000"
  ["Email RAG"]="192.168.1.110:3000"
  ["Audio Pipeline"]="192.168.1.74:8090"
  ["Home Assistant"]="192.168.1.14:8123"
  ["CompreFace"]="192.168.1.69:8000"
  ["Double-Take"]="192.168.1.69:3000"
  ["Infisical"]="192.168.1.69:8093"
)

for svc in "${!STANDALONE[@]}"; do
  addr="${STANDALONE[$svc]}"
  ip=$(echo "$addr" | cut -d: -f1)
  port=$(echo "$addr" | cut -d: -f2)

  if timeout 3 bash -c "echo >/dev/tcp/$ip/$port" 2>/dev/null; then
    status="${GREEN}✓ UP${NC}"
  else
    status="${RED}✗ DOWN${NC}"
  fi

  printf "%-25s %-18s %-20b\n" "$svc" "$addr" "$status"
done

# --- NFS Mounts ---
echo ""
echo -e "${CYAN}=== NFS STATUS ===${NC}"
if ping -c 1 -W 2 192.168.1.11 &>/dev/null; then
  echo -e "  NAS (.11): ${GREEN}✓ Reachable${NC}"
else
  echo -e "  NAS (.11): ${RED}✗ Unreachable${NC}"
fi

echo ""
echo "============================================"
echo " Health check complete"
echo "============================================"
