#!/usr/bin/env bash
# ============================================================
# Layer 3: Off-site Backup → Google Drive
# Syncs NAS backup directory to encrypted Google Drive folder
# via rclone (already configured as gdrive: on workstation).
#
# Run weekly from workstation:
#   0 5 * * 0 /home/chris/uptonx-homelab/scripts/backups/offsite-gdrive.sh
#
# Rclone crypt remote setup (one-time):
#   rclone config
#   → New remote → name: gdrive-crypt
#   → Type: crypt → Remote: gdrive:homelab-backups
#   → Encrypt filenames: standard → Enter passwords
# ============================================================
set -euo pipefail

NAS_USER="chris-admin"
NAS_HOST="192.168.1.11"
NAS_BACKUP_PATH="/volume1/UptonX/backups"
LOCAL_MIRROR="/tmp/gdrive-backup-staging"
GDRIVE_REMOTE="gdrive:homelab-backups"  # or gdrive-crypt: for encrypted
KEEP_DAYS=14  # fits within Google Drive free 15GB tier (~13GB at 14d)

log() { echo "[$(date '+%H:%M:%S')] $1"; }

log "=== Off-site backup to Google Drive ==="

# Pull latest from NAS to local staging
mkdir -p "$LOCAL_MIRROR"
log "Pulling backups from NAS..."
rsync -az "${NAS_USER}@${NAS_HOST}:${NAS_BACKUP_PATH}/" "$LOCAL_MIRROR/"

# Sync to Google Drive
log "Uploading to $GDRIVE_REMOTE ..."
rclone sync "$LOCAL_MIRROR/" "$GDRIVE_REMOTE/" \
  --transfers 4 \
  --checkers 8 \
  --min-age 0 \
  --max-age "${KEEP_DAYS}d" \
  --log-level INFO \
  --stats-one-line

# Clean up old files on Google Drive
log "Pruning remote files older than ${KEEP_DAYS} days..."
rclone delete "$GDRIVE_REMOTE/" --min-age "${KEEP_DAYS}d" --log-level INFO

# Clean up local staging
rm -rf "$LOCAL_MIRROR"

log "=== Off-site backup complete ==="
