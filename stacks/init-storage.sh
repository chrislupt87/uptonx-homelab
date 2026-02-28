#!/usr/bin/env bash
# Run on Aux 2 before deploying any stacks.
# Mounts the NAS via NFS and creates persistent volume directories.
set -euo pipefail

NAS_IP="192.168.1.11"
# NOTE: Adjust the NFS export path below to match your NAS share.
# Common paths: /volume1/docker, /mnt/storage/docker, /export/stacks
NFS_EXPORT="${NAS_IP}:/volume1/docker"
MOUNT_POINT="/mnt/nas"

SERVICES=(traefik portainer technitium vaultwarden uptime-kuma watchtower)

echo "==> Creating mount point ${MOUNT_POINT}..."
mkdir -p "${MOUNT_POINT}"

echo "==> Adding NFS mount to /etc/fstab..."
if ! grep -q "${NFS_EXPORT}" /etc/fstab; then
  echo "${NFS_EXPORT} ${MOUNT_POINT} nfs defaults,soft,timeo=150,retrans=3 0 0" >> /etc/fstab
  echo "    Entry added to /etc/fstab."
else
  echo "    NFS entry already in /etc/fstab, skipping."
fi

echo "==> Mounting NAS..."
mount "${MOUNT_POINT}" 2>/dev/null || echo "    Already mounted or mount failed — check manually."

echo "==> Creating stack data directories on NAS..."
for svc in "${SERVICES[@]}"; do
  mkdir -p "${MOUNT_POINT}/stacks/${svc}"
  echo "    Created ${MOUNT_POINT}/stacks/${svc}"
done

echo ""
echo "==> Storage setup complete. Verify with: df -h ${MOUNT_POINT}"
