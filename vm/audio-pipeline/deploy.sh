#!/usr/bin/env bash
set -euo pipefail

# Audio Pipeline Deploy Script
# Builds images on workstation and deploys to MSI (.74)
#
# Usage:
#   ./deploy.sh          # deploy both frontend + backend
#   ./deploy.sh frontend # deploy frontend only
#   ./deploy.sh backend  # deploy backend only

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MSI="root@192.168.1.74"
STACK_DIR="/opt/stacks/audio-pipeline"
COMPONENT="${1:-all}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
err() { echo -e "${RED}[deploy]${NC} $1" >&2; exit 1; }

deploy_frontend() {
    log "Building frontend..."
    cd "$SCRIPT_DIR/frontend"
    npm run build --silent

    log "Building frontend Docker image..."
    docker build -t audio-pipeline-frontend:latest . -q

    log "Transferring to MSI..."
    docker save audio-pipeline-frontend:latest | ssh "$MSI" "docker load" -q

    log "Syncing config files..."
    scp -q "$SCRIPT_DIR/docker-compose.yml" "$MSI:$STACK_DIR/docker-compose.yml"
    scp -q "$SCRIPT_DIR/frontend/nginx.conf" "$MSI:$STACK_DIR/frontend/nginx.conf"

    log "Restarting frontend container..."
    ssh "$MSI" "cd $STACK_DIR && docker compose up -d audio_frontend"

    log "Frontend deployed."
}

deploy_backend() {
    log "Building backend Docker image (this takes a while on first build)..."
    cd "$SCRIPT_DIR/backend"
    docker build -t audio-pipeline-api:latest . -q

    log "Transferring to MSI (large image ~5GB)..."
    docker save audio-pipeline-api:latest | ssh "$MSI" "docker load"

    log "Syncing config files..."
    scp -q "$SCRIPT_DIR/docker-compose.yml" "$MSI:$STACK_DIR/docker-compose.yml"

    log "Restarting API container..."
    ssh "$MSI" "cd $STACK_DIR && docker compose up -d audio_api"

    log "Backend deployed."
}

case "$COMPONENT" in
    frontend|fe)
        deploy_frontend
        ;;
    backend|be|api)
        deploy_backend
        ;;
    all)
        deploy_backend
        deploy_frontend
        ;;
    *)
        err "Unknown component: $COMPONENT (use frontend, backend, or all)"
        ;;
esac

log "Checking container status..."
ssh "$MSI" "cd $STACK_DIR && docker compose ps"
echo ""
log "Done."
