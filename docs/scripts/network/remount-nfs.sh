#!/usr/bin/env bash
set -euo pipefail

# Unmount stale NFS and remount all NFS shares
#
# NFS Shares:
#   - email-rag VM (.110): 192.168.1.11:/volume1/UptonX/email-rag → /mnt/nfs/volumes/email-rag
#   - Frigate on aux (.18): 192.168.1.11:/volume1/UptonX/frigate → /mnt/nfs/frigate
#
# Usage: ./remount-nfs.sh [target]
#   target: all (default), email-rag, frigate

NAS_IP="192.168.1.11"
TARGET="${1:-all}"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "============================================"
echo " NFS Remount — Target: $TARGET"
echo "============================================"

# Check NAS reachability first
echo ""
echo "[1] Checking NAS reachability ($NAS_IP) ..."
if ! ping -c 2 -W 3 "$NAS_IP" &>/dev/null; then
  echo -e "${RED}ERROR: NAS at $NAS_IP is unreachable!${NC}"
  echo "  - Is the NAS powered on?"
  echo "  - Check network connectivity"
  exit 1
fi
echo -e "  ${GREEN}NAS is reachable${NC}"

# --- Email RAG NFS (VM 401 on ai, .110) ---
remount_email_rag() {
  local HOST="chris@192.168.1.110"
  local MOUNT="/mnt/nfs/volumes/email-rag"
  local SHARE="$NAS_IP:/volume1/UptonX/email-rag"

  echo ""
  echo "[Email RAG] Remounting $SHARE on .110 ..."

  ssh "$HOST" bash -s <<NFSEOF
set -euo pipefail

echo "  Checking current mount ..."
if mountpoint -q "$MOUNT" 2>/dev/null; then
  if timeout 5 ls "$MOUNT" &>/dev/null; then
    echo "  Mount is healthy, skipping"
    exit 0
  else
    echo "  Mount is stale, force unmounting ..."
    sudo umount -l "$MOUNT"
  fi
fi

echo "  Mounting $SHARE → $MOUNT ..."
sudo mkdir -p "$MOUNT"
sudo mount -t nfs -o vers=3,soft,timeo=30 "$SHARE" "$MOUNT"

if mountpoint -q "$MOUNT"; then
  echo "  ✓ Mounted successfully"
  ls "$MOUNT" | head -5
else
  echo "  ✗ Mount failed!"
  exit 1
fi
NFSEOF
}

# --- Frigate NFS (aux host .18) ---
remount_frigate() {
  local HOST="root@192.168.1.18"
  local MOUNT="/mnt/nfs/frigate"
  local SHARE="$NAS_IP:/volume1/UptonX/frigate"

  echo ""
  echo "[Frigate] Remounting $SHARE on .18 ..."

  ssh "$HOST" bash -s <<NFSEOF
set -euo pipefail

echo "  Checking current mount ..."
if mountpoint -q "$MOUNT" 2>/dev/null; then
  if timeout 5 ls "$MOUNT" &>/dev/null; then
    echo "  Mount is healthy, skipping"
    exit 0
  else
    echo "  Mount is stale, force unmounting ..."
    umount -l "$MOUNT"
  fi
fi

echo "  Mounting $SHARE → $MOUNT ..."
mkdir -p "$MOUNT"
mount -t nfs -o vers=3,soft,timeo=30 "$SHARE" "$MOUNT"

if mountpoint -q "$MOUNT"; then
  echo "  ✓ Mounted successfully"
  ls "$MOUNT" | head -5
else
  echo "  ✗ Mount failed!"
  exit 1
fi
NFSEOF
}

case "$TARGET" in
  all)
    remount_email_rag
    remount_frigate
    ;;
  email-rag)
    remount_email_rag
    ;;
  frigate)
    remount_frigate
    ;;
  *)
    echo "Unknown target: $TARGET"
    echo "Usage: $0 [all|email-rag|frigate]"
    exit 1
    ;;
esac

echo ""
echo "============================================"
echo " NFS remount complete"
echo "============================================"
