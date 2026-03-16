#!/usr/bin/env bash
# ============================================================
# Infisical Secret Sync
# Pulls secrets from Infisical and writes .env files for each service.
# Run from workstation or any machine with infisical CLI installed.
#
# Prerequisites:
#   1. Install CLI: curl -1sLf https://dl.cloudsmith.io/public/infisical/infisical-cli/setup.deb.sh | sudo bash && sudo apt install infisical
#   2. Login: infisical login --domain https://infisical.uptonx.com
#   3. Create a Machine Identity in Infisical with access to all projects
#      OR use `infisical login` interactively
#
# Usage:
#   ./infisical-sync.sh                    # Sync all services
#   ./infisical-sync.sh traefik            # Sync one service
#   ./infisical-sync.sh --deploy traefik   # Sync + deploy to host
# ============================================================
set -euo pipefail

INFISICAL_URL="https://infisical.uptonx.com"
PROJECT_SLUG="homelab"  # Set this to your Infisical project slug

# Service → host mapping (for --deploy)
declare -A HOST_MAP=(
  [traefik]="root@192.168.1.15:/opt/traefik/.env"
  [authentik]="root@192.168.1.16:/opt/authentik/.env"
  [frigate]="root@192.168.1.18:/etc/frigate/.env"
  [video-ai]="root@192.168.1.69:/opt/video-ai/.env"
  [infisical]="root@192.168.1.69:/opt/infisical/.env"
  [audio]="root@192.168.1.74:/opt/stacks/audio-pipeline/.env"
  [email-rag]="chris@192.168.1.110:/opt/email-rag/secrets/email-rag.env"
)

DEPLOY=false
TARGET=""

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --deploy) DEPLOY=true; shift ;;
    *) TARGET="$1"; shift ;;
  esac
done

sync_service() {
  local svc="$1"
  local env_file="/tmp/infisical-${svc}.env"

  echo "=== Syncing: $svc ==="
  infisical export \
    --domain "$INFISICAL_URL" \
    --projectId "$PROJECT_SLUG" \
    --env prod \
    --path "/$svc" \
    --format dotenv \
    > "$env_file"

  local line_count
  line_count=$(wc -l < "$env_file")
  echo "  Wrote $line_count secrets to $env_file"

  if $DEPLOY && [[ -n "${HOST_MAP[$svc]:-}" ]]; then
    local dest="${HOST_MAP[$svc]}"
    local host="${dest%%:*}"
    local path="${dest#*:}"
    echo "  Deploying to $dest ..."
    scp -q "$env_file" "$dest"
    ssh "$host" "chmod 600 $path"
    echo "  Done."
  fi

  rm -f "$env_file"
}

if [[ -n "$TARGET" ]]; then
  sync_service "$TARGET"
else
  for svc in "${!HOST_MAP[@]}"; do
    sync_service "$svc"
  done
fi

echo ""
echo "=== Sync complete ==="
