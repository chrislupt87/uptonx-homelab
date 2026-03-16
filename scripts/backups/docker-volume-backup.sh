#!/usr/bin/env bash
# ============================================================
# Layer 2: Docker Volume Backups → NAS
# Dumps critical Docker volumes (databases, configs) and
# rsyncs to NAS (.11) for off-host backup.
#
# Deploy this script to each host that runs stateful containers.
# Run via cron: 0 3 * * * /opt/scripts/docker-volume-backup.sh
#
# The script auto-detects which services are on the current host
# and only backs up what's relevant.
# ============================================================
set -euo pipefail

NAS_USER="chris-admin"
NAS_HOST="192.168.1.11"
NAS_PATH="/volume1/UptonX/backups"
LOCAL_STAGING="/tmp/docker-backups"
HOSTNAME=$(hostname)
DATE=$(date +%Y-%m-%d)
KEEP_DAYS=14

mkdir -p "$LOCAL_STAGING"

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# ---- PostgreSQL dump helper ----
dump_postgres() {
  local container="$1"
  local db="$2"
  local user="$3"
  local outfile="$LOCAL_STAGING/${container}-${DATE}.sql.gz"

  if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    log "Dumping $container ($db)..."
    docker exec "$container" pg_dump -U "$user" "$db" | gzip > "$outfile"
    log "  → $(du -h "$outfile" | cut -f1)"
  fi
}

# ---- Volume tar helper ----
backup_volume() {
  local volume="$1"
  local label="$2"
  local outfile="$LOCAL_STAGING/${label}-${DATE}.tar.gz"

  if docker volume inspect "$volume" &>/dev/null; then
    log "Backing up volume $volume..."
    docker run --rm -v "${volume}:/data:ro" -v "$LOCAL_STAGING:/backup" \
      alpine tar czf "/backup/${label}-${DATE}.tar.gz" -C /data .
    log "  → $(du -h "$outfile" | cut -f1)"
  fi
}

# ---- Directory tar helper ----
backup_dir() {
  local dir="$1"
  local label="$2"
  local outfile="$LOCAL_STAGING/${label}-${DATE}.tar.gz"

  if [[ -d "$dir" ]]; then
    log "Backing up $dir..."
    tar czf "$outfile" -C "$(dirname "$dir")" "$(basename "$dir")" 2>/dev/null
    log "  → $(du -h "$outfile" | cut -f1)"
  fi
}

log "=== Docker volume backup on $HOSTNAME ($DATE) ==="

# ---- ai NUC (.69) ----
# CompreFace PostgreSQL
dump_postgres "compreface-postgres" "frs" "postgres"

# Infisical PostgreSQL
dump_postgres "infisical-postgres" "infisical" "infisical"

# Qdrant vector data
backup_volume "video-ai_qdrant_data" "qdrant"

# Double-Take config
backup_dir "/opt/video-ai/double-take" "double-take-config"

# n8n data
backup_volume "video-ai_n8n_data" "n8n"

# ---- aux (.18) ----
# Frigate config (not recordings — those have their own archive)
backup_dir "/etc/frigate" "frigate-config"

# Frigate DB
if [[ -f "/media/frigate/frigate.db" ]]; then
  log "Backing up Frigate DB..."
  cp "/media/frigate/frigate.db" "$LOCAL_STAGING/frigate-db-${DATE}.db"
  gzip "$LOCAL_STAGING/frigate-db-${DATE}.db"
  log "  → $(du -h "$LOCAL_STAGING/frigate-db-${DATE}.db.gz" | cut -f1)"
fi

# ---- aux2 CTs (accessed from host or within CT) ----
# Traefik ACME certs
backup_dir "/opt/traefik/letsencrypt" "traefik-acme"

# Authentik PostgreSQL
dump_postgres "authentik-postgresql" "authentik" "authentik"

# Authentik media
backup_volume "authentik_media" "authentik-media"

# ---- msi (.74) ----
# Audio pipeline SQLite
if [[ -f "/opt/stacks/audio-pipeline/data/jobs.db" ]]; then
  log "Backing up audio pipeline DB..."
  cp "/opt/stacks/audio-pipeline/data/jobs.db" "$LOCAL_STAGING/audio-jobs-${DATE}.db"
  gzip "$LOCAL_STAGING/audio-jobs-${DATE}.db"
fi

# ---- email-rag VM (.110) ----
# PostgreSQL (native, not Docker)
if command -v pg_dump &>/dev/null; then
  log "Dumping email-rag PostgreSQL..."
  sudo -u postgres pg_dump email_rag | gzip > "$LOCAL_STAGING/email-rag-db-${DATE}.sql.gz"
  log "  → $(du -h "$LOCAL_STAGING/email-rag-db-${DATE}.sql.gz" | cut -f1)"
fi

# ---- Swarm manager (.23) ----
# Grafana data
backup_volume "grafana_data" "grafana"

# Prometheus data
backup_volume "grafana_prom_data" "prometheus"

# Loki data
backup_volume "grafana_loki_data" "loki"

# Portainer data
backup_volume "portainer_portainer_data" "portainer"

# ============================================================
# Sync to NAS
# ============================================================
BACKUP_COUNT=$(find "$LOCAL_STAGING" -name "*-${DATE}*" -type f | wc -l)

if [[ $BACKUP_COUNT -gt 0 ]]; then
  log "Syncing $BACKUP_COUNT files to NAS..."
  NAS_DEST="${NAS_USER}@${NAS_HOST}:${NAS_PATH}/${HOSTNAME}/"
  ssh "$NAS_USER@$NAS_HOST" "mkdir -p ${NAS_PATH}/${HOSTNAME}" 2>/dev/null || true
  rsync -az --progress "$LOCAL_STAGING/"*"-${DATE}"* "$NAS_DEST"
  log "Sync complete."

  # Clean up old backups on NAS
  log "Pruning backups older than $KEEP_DAYS days on NAS..."
  ssh "$NAS_USER@$NAS_HOST" "find ${NAS_PATH}/${HOSTNAME} -type f -mtime +${KEEP_DAYS} -delete" 2>/dev/null || true
fi

# Clean up local staging
rm -rf "$LOCAL_STAGING"

log "=== Backup complete ==="
