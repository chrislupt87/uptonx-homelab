#!/bin/bash
# ============================================================
# Authentik SSO — CT 103 on aux2 (192.168.1.80)
# Creates LXC, installs Docker, deploys Authentik
# Run this ON aux2 as root
# ============================================================
set -euo pipefail

CT_ID=103
CT_IP="192.168.1.16"
CT_GW="192.168.1.1"
CT_HOSTNAME="authentik"
CT_PASSWORD="Terry87!"
STORAGE="local-lvm"
TEMPLATE="local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"

echo "=== Creating CT $CT_ID ($CT_HOSTNAME) ==="

# Create the container
pct create $CT_ID $TEMPLATE \
  --hostname $CT_HOSTNAME \
  --password "$CT_PASSWORD" \
  --cores 2 \
  --memory 2048 \
  --swap 512 \
  --rootfs $STORAGE:8 \
  --net0 name=eth0,bridge=vmbr0,ip=$CT_IP/24,gw=$CT_GW \
  --features keyctl=1,nesting=1 \
  --unprivileged 0 \
  --start 0

# Add AppArmor unconfined for Docker-in-LXC
cat >> /etc/pve/lxc/$CT_ID.conf <<EOF
lxc.apparmor.profile: unconfined
EOF

echo "=== Starting CT $CT_ID ==="
pct start $CT_ID
sleep 5

echo "=== Installing Docker ==="
pct exec $CT_ID -- bash -c '
  # Enable root SSH
  sed -i "s/#PermitRootLogin.*/PermitRootLogin yes/" /etc/ssh/sshd_config
  systemctl restart sshd

  # Install Docker
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

  # Remove apparmor (conflicts with Docker in LXC)
  apt-get remove -y apparmor || true
'

echo "=== CT $CT_ID ready ==="
echo "Next steps:"
echo "  1. Copy docker-compose.yml and .env to CT $CT_ID:/opt/authentik/"
echo "  2. pct exec $CT_ID -- bash -c 'mkdir -p /opt/authentik && cd /opt/authentik && docker compose up -d'"
echo "  3. Access initial setup at https://auth.uptonx.com/if/flow/initial-setup/"
echo ""
echo "To copy files from this host:"
echo "  pct push $CT_ID /path/to/docker-compose.yml /opt/authentik/docker-compose.yml"
echo "  pct push $CT_ID /path/to/.env /opt/authentik/.env"
