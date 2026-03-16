#!/usr/bin/env bash
# ============================================================
# Deploy backup crons to all hosts
# Run from workstation
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/docker-volume-backup.sh"

# Hosts that run stateful Docker containers
declare -A HOSTS=(
  [aux]="root@192.168.1.18"        # Frigate
  [ai]="root@192.168.1.69"         # Video AI, Infisical, Uptime Kuma
  [msi]="root@192.168.1.74"        # Audio pipeline
  [email-rag]="chris@192.168.1.110" # Email RAG VM
)

# LXC hosts — backup script runs inside CTs via pct exec
declare -A LXC_HOSTS=(
  [aux2-ct102]="root@192.168.1.80:102"   # Traefik (acme certs)
  [aux2-ct103]="root@192.168.1.80:103"   # Authentik
  [aux-ct106]="root@192.168.1.18:106"    # Swarm manager (Grafana, Portainer)
)

echo "=== Deploying docker-volume-backup.sh to hosts ==="

for name in "${!HOSTS[@]}"; do
  host="${HOSTS[$name]}"
  echo ""
  echo "--- $name ($host) ---"
  ssh "$host" "mkdir -p /opt/scripts"
  scp -q "$BACKUP_SCRIPT" "$host:/opt/scripts/docker-volume-backup.sh"
  ssh "$host" "chmod +x /opt/scripts/docker-volume-backup.sh"

  # Install cron (3 AM daily, staggered by 10 min per host)
  case $name in
    aux)      MINUTE=0  ;;
    ai)       MINUTE=10 ;;
    msi)      MINUTE=20 ;;
    email-rag) MINUTE=30 ;;
  esac

  CRON_LINE="$MINUTE 3 * * * /opt/scripts/docker-volume-backup.sh >> /var/log/docker-backup.log 2>&1"
  ssh "$host" "echo '$CRON_LINE' > /etc/cron.d/docker-volume-backup && chmod 644 /etc/cron.d/docker-volume-backup"
  echo "  Cron installed: 03:$(printf '%02d' $MINUTE) daily"
done

echo ""
echo "=== Deploying to LXC containers ==="

for name in "${!LXC_HOSTS[@]}"; do
  entry="${LXC_HOSTS[$name]}"
  host="${entry%%:*}"
  ctid="${entry##*:}"
  echo ""
  echo "--- $name (CT $ctid via $host) ---"

  # Push script into CT
  scp -q "$BACKUP_SCRIPT" "$host:/tmp/docker-volume-backup.sh"
  ssh "$host" "pct push $ctid /tmp/docker-volume-backup.sh /opt/scripts/docker-volume-backup.sh"
  ssh "$host" "pct exec $ctid -- chmod +x /opt/scripts/docker-volume-backup.sh"
  ssh "$host" "rm /tmp/docker-volume-backup.sh"

  # Install cron inside CT
  CRON_LINE="40 3 * * * /opt/scripts/docker-volume-backup.sh >> /var/log/docker-backup.log 2>&1"
  ssh "$host" "pct exec $ctid -- bash -c \"echo '$CRON_LINE' > /etc/cron.d/docker-volume-backup && chmod 644 /etc/cron.d/docker-volume-backup\""
  echo "  Cron installed: 03:40 daily"
done

echo ""
echo "=== Workstation cron (off-site gdrive) ==="
GDRIVE_CRON="0 5 * * 0 $SCRIPT_DIR/offsite-gdrive.sh >> /var/log/gdrive-backup.log 2>&1"
echo "$GDRIVE_CRON" | sudo tee /etc/cron.d/offsite-gdrive-backup > /dev/null
sudo chmod 644 /etc/cron.d/offsite-gdrive-backup
echo "  Cron installed: Sunday 05:00 weekly"

echo ""
echo "=== All backup crons deployed ==="
echo ""
echo "Schedule summary:"
echo "  02:00  PBS snapshots (all Proxmox hosts → .19)"
echo "  03:00  Docker volumes: aux (.18) → NAS"
echo "  03:10  Docker volumes: ai (.69) → NAS"
echo "  03:20  Docker volumes: msi (.74) → NAS"
echo "  03:30  Docker volumes: email-rag (.110) → NAS"
echo "  03:40  Docker volumes: LXC CTs → NAS"
echo "  05:00  Off-site: NAS → Google Drive (Sundays)"
