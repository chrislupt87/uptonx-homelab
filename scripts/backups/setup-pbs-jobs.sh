#!/usr/bin/env bash
# ============================================================
# Layer 1: Proxmox → PBS Backup Jobs
# Run this ONCE on each Proxmox host to create scheduled backup
# jobs that send CT/VM snapshots to PBS (.19)
#
# Prerequisites:
#   - PBS storage already added to each host in Proxmox UI
#     Datacenter → Storage → Add → Proxmox Backup Server
#     Server: 192.168.1.19, Datastore: main, Username: root@pam
#   - The storage name should be "pbs" (adjust PBS_STORAGE below if different)
#
# Usage: Run on each Proxmox host as root
#   bash setup-pbs-jobs.sh
# ============================================================
set -euo pipefail

PBS_STORAGE="pbs"
SCHEDULE="02:00"          # 2 AM daily
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=2
MAIL_TO="root"
COMPRESS="zstd"
MODE="snapshot"

HOSTNAME=$(hostname)

echo "=== Setting up PBS backup jobs on $HOSTNAME ==="

# Detect which CTs and VMs exist on this host
CTS=$(pct list 2>/dev/null | tail -n+2 | awk '{print $1}' | tr '\n' ',' | sed 's/,$//')
VMS=$(qm list 2>/dev/null | tail -n+2 | awk '{print $1}' | tr '\n' ',' | sed 's/,$//')

VMID_LIST=""
[[ -n "$CTS" ]] && VMID_LIST="$CTS"
[[ -n "$VMS" && -n "$VMID_LIST" ]] && VMID_LIST="$VMID_LIST,$VMS"
[[ -n "$VMS" && -z "$VMID_LIST" ]] && VMID_LIST="$VMS"

if [[ -z "$VMID_LIST" ]]; then
  echo "No CTs or VMs found on $HOSTNAME, skipping."
  exit 0
fi

echo "  CTs: ${CTS:-none}"
echo "  VMs: ${VMS:-none}"
echo "  Backing up: $VMID_LIST"

# Check if PBS storage exists
if ! pvesm status | grep -q "^${PBS_STORAGE}"; then
  echo "ERROR: PBS storage '$PBS_STORAGE' not found. Add it in Proxmox UI first:"
  echo "  Datacenter → Storage → Add → Proxmox Backup Server"
  echo "  Server: 192.168.1.19 | Datastore: main | Username: root@pam"
  exit 1
fi

# Create the backup job
# Using pvesh to create a vzdump job
JOB_ID="backup-${HOSTNAME}-daily"

# Remove existing job with same ID if present
pvesh get /cluster/backup 2>/dev/null | grep -q "$JOB_ID" && \
  echo "  Removing existing job $JOB_ID..." && \
  pvesh delete "/cluster/backup/$JOB_ID" 2>/dev/null || true

echo "  Creating backup job: $JOB_ID"
pvesh create /cluster/backup \
  --id "$JOB_ID" \
  --schedule "$SCHEDULE" \
  --storage "$PBS_STORAGE" \
  --vmid "$VMID_LIST" \
  --compress "$COMPRESS" \
  --mode "$MODE" \
  --mailnotification failure \
  --mailto "$MAIL_TO" \
  --enabled 1 \
  --prune-backups "keep-daily=$KEEP_DAILY,keep-weekly=$KEEP_WEEKLY,keep-monthly=$KEEP_MONTHLY" \
  --notes-template "{{guestname}} auto-backup" \
  2>/dev/null || {
    # Fallback: create via vzdump cron if pvesh API differs
    echo "  pvesh API failed, creating vzdump cron instead..."
    CRON_LINE="0 2 * * * root vzdump $VMID_LIST --storage $PBS_STORAGE --compress $COMPRESS --mode $MODE --prune-backups keep-daily=$KEEP_DAILY,keep-weekly=$KEEP_WEEKLY,keep-monthly=$KEEP_MONTHLY --quiet 1"
    CRON_FILE="/etc/cron.d/pbs-backup-${HOSTNAME}"
    echo "$CRON_LINE" > "$CRON_FILE"
    chmod 644 "$CRON_FILE"
    echo "  Created $CRON_FILE"
  }

echo ""
echo "=== Done. Backup schedule: daily at $SCHEDULE ==="
echo "  Retention: $KEEP_DAILY daily, $KEEP_WEEKLY weekly, $KEEP_MONTHLY monthly"
echo "  Storage: $PBS_STORAGE (192.168.1.19)"
echo ""
echo "Verify with: pvesh get /cluster/backup"
echo "Manual run:  vzdump $VMID_LIST --storage $PBS_STORAGE --compress $COMPRESS --mode $MODE"
