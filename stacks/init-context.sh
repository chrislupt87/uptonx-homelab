#!/usr/bin/env bash
# Run once on workstation before anything else.
# After this all docker commands target Aux 2 automatically.
set -euo pipefail

REMOTE_HOST="ssh://root@192.168.1.80"
CONTEXT_NAME="aux2"

echo "==> Creating Docker context '${CONTEXT_NAME}' pointing to ${REMOTE_HOST}..."
docker context create "${CONTEXT_NAME}" --docker "host=${REMOTE_HOST}" 2>/dev/null \
  || echo "Context '${CONTEXT_NAME}' already exists, updating..." \
  && docker context update "${CONTEXT_NAME}" --docker "host=${REMOTE_HOST}"

echo "==> Switching active context to '${CONTEXT_NAME}'..."
docker context use "${CONTEXT_NAME}"

echo "==> Verifying connection to remote Docker host..."
docker info

echo ""
echo "==> Done. All docker commands now target Aux 2 (192.168.1.80)."
