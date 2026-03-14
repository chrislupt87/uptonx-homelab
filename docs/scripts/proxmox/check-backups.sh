#!/usr/bin/env bash
set -euo pipefail

# Verify PBS backups exist and are recent for all VMs/CTs
#
# Checks each Proxmox host for backup status in PBS datastore
# Also checks NAS-based Docker volume backups
#
# Usage: ./check-backups.sh

PBS_IP="192.168.1.19"
NAS_IP="192.168.1.11"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo "============================================"
echo " UptonX Backup Verification"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

# --- PBS Reachability ---
echo ""
echo -e "${CYAN}=== PBS STATUS ===${NC}"
if ping -c 1 -W 3 "$PBS_IP" &>/dev/null; then
  echo -e "  PBS ($PBS_IP): ${GREEN}✓ Reachable${NC}"
else
  echo -e "  PBS ($PBS_IP): ${RED}✗ Unreachable — backups may be stale!${NC}"
fi

# --- Check PBS backups per host ---
echo ""
echo -e "${CYAN}=== PBS BACKUPS (VM/CT Snapshots) ===${NC}"
printf "%-12s %-8s %-25s %-10s %-10s\n" "HOST" "VMID" "LATEST BACKUP" "SIZE" "AGE"
printf "%-12s %-8s %-25s %-10s %-10s\n" "----" "----" "-------------" "----" "---"

declare -A HOST_MAP=(
  ["aux"]="root@192.168.1.18"
  ["helm"]="root@192.168.1.77"
  ["aux2"]="root@192.168.1.80"
  ["ai"]="root@192.168.1.69"
)

NOW=$(date +%s)

for host in aux helm aux2 ai; do
  pve="${HOST_MAP[$host]}"

  # List all VMIDs with backups on this host
  CONTENT=$(ssh "$pve" "pvesh get /nodes/\$(hostname)/storage/pbs/content --output-format json 2>/dev/null" || echo "[]")

  if [ "$CONTENT" = "[]" ]; then
    printf "%-12s %-8s %-25s %-10s %-10s\n" "$host" "—" "NO BACKUPS FOUND" "—" "—"
    continue
  fi

  echo "$CONTENT" | python3 -c "
import json, sys, time
data = json.load(sys.stdin)
host = '$host'
now = $NOW

# Group by vmid, find latest
by_vmid = {}
for b in data:
    vmid = b.get('vmid', '?')
    ctime = b.get('ctime', 0)
    if vmid not in by_vmid or ctime > by_vmid[vmid]['ctime']:
        by_vmid[vmid] = b

for vmid in sorted(by_vmid.keys()):
    b = by_vmid[vmid]
    ctime = b.get('ctime', 0)
    size_gb = b.get('size', 0) / (1024**3)
    age_hours = (now - ctime) / 3600

    if age_hours < 26:
        age_str = f'{age_hours:.0f}h ✓'
    elif age_hours < 72:
        age_str = f'{age_hours/24:.1f}d ⚠'
    else:
        age_str = f'{age_hours/24:.0f}d ✗'

    date_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(ctime))
    print(f'{host:<12} {vmid:<8} {date_str:<25} {size_gb:<10.1f} {age_str}')
" 2>/dev/null || printf "%-12s %-8s %-25s %-10s %-10s\n" "$host" "?" "PARSE ERROR" "?" "?"

done

# --- Check NAS Docker volume backups ---
echo ""
echo -e "${CYAN}=== NAS DOCKER VOLUME BACKUPS ===${NC}"

if ! ping -c 1 -W 3 "$NAS_IP" &>/dev/null; then
  echo -e "  NAS ($NAS_IP): ${RED}✗ Unreachable${NC}"
else
  echo -e "  NAS ($NAS_IP): ${GREEN}✓ Reachable${NC}"
  echo ""

  # Check backup directories on each host
  for host_info in "ai:root@192.168.1.69" "aux:root@192.168.1.18" "msi:root@192.168.1.74"; do
    host=$(echo "$host_info" | cut -d: -f1)
    ssh_addr=$(echo "$host_info" | cut -d: -f2)

    # Check if backup script ran recently (look at NAS backup dir)
    LATEST=$(ssh "$ssh_addr" "ls -t /mnt/nfs/backups/$host/ 2>/dev/null | head -1" 2>/dev/null || echo "")
    if [ -n "$LATEST" ]; then
      echo -e "  ${GREEN}✓${NC} $host: latest backup dir = $LATEST"
    else
      echo -e "  ${YELLOW}⚠${NC} $host: no backups found on NAS (check /mnt/nfs/backups/$host/)"
    fi
  done
fi

echo ""
echo "============================================"
echo " Backup check complete"
echo "============================================"
echo ""
echo "PBS Web UI: https://$PBS_IP:8007"
echo ""
