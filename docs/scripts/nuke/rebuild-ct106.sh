#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════╗
# ║  DESTRUCTIVE: Full teardown and rebuild of CT 106           ║
# ║  Primary Swarm Manager on aux (.18)                         ║
# ║                                                             ║
# ║  This script will:                                          ║
# ║    1. Destroy CT 106                                        ║
# ║    2. Recreate it with correct LXC config                   ║
# ║    3. Install Docker                                        ║
# ║    4. Initialize a new Swarm (or rejoin existing)           ║
# ║    5. Recreate overlay networks                             ║
# ║    6. Redeploy all stacks                                   ║
# ║                                                             ║
# ║  WARNING: All other managers/workers must rejoin afterward  ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Usage: ./rebuild-ct106.sh
# Prerequisites: SSH access to aux (.18) as root

PVE_AUX="root@192.168.1.18"
MGR1_IP="192.168.1.23"
GATEWAY="192.168.1.1"
ROOT_PASSWORD="Terry87!"
CT_TEMPLATE="local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
CTID=106

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${RED}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║        DESTRUCTIVE: REBUILD CT 106 (SWARM MANAGER)     ║${NC}"
echo -e "${RED}║                                                        ║${NC}"
echo -e "${RED}║  This will destroy and recreate CT 106 on aux (.18).   ║${NC}"
echo -e "${RED}║  ALL swarm state will be lost. All nodes must rejoin.  ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Press ENTER to continue, or Ctrl+C to abort ..."
read -r

echo "Are you REALLY sure? Type 'REBUILD' to confirm:"
read -r CONFIRM
if [ "$CONFIRM" != "REBUILD" ]; then
  echo "Aborted."
  exit 1
fi

echo ""
echo "============================================"
echo " Phase 1: Destroy existing CT 106"
echo "============================================"

ssh "$PVE_AUX" bash -s <<DESTROYEOF
set -euo pipefail
if pct status $CTID &>/dev/null; then
  echo "Stopping CT $CTID ..."
  pct stop $CTID 2>/dev/null || true
  sleep 3
  echo "Destroying CT $CTID ..."
  pct destroy $CTID --force
  echo "CT $CTID destroyed."
else
  echo "CT $CTID does not exist, skipping destroy."
fi
DESTROYEOF

echo ""
echo "============================================"
echo " Phase 2: Create new CT 106"
echo "============================================"

ssh "$PVE_AUX" bash -s <<CREATEEOF
set -euo pipefail

echo "Creating CT $CTID ..."
pct create $CTID $CT_TEMPLATE \
  --hostname swarm-manager \
  --cores 2 \
  --memory 2048 \
  --rootfs local-lvm:20 \
  --net0 name=eth0,bridge=vmbr0,ip=$MGR1_IP/24,gw=$GATEWAY \
  --features keyctl=1,nesting=1 \
  --unprivileged 0 \
  --password "$ROOT_PASSWORD" \
  --start 0

# AppArmor unconfined
echo 'lxc.apparmor.profile: unconfined' >> /etc/pve/lxc/$CTID.conf

echo "Starting CT $CTID ..."
pct start $CTID
sleep 5
echo "CT $CTID created and started."
CREATEEOF

echo ""
echo "============================================"
echo " Phase 3: Install Docker"
echo "============================================"

ssh "$PVE_AUX" pct exec $CTID -- bash -s <<'DOCKEREOF'
set -euo pipefail

# Enable root SSH
sed -i 's/#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
systemctl restart sshd || true

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
> /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin ufw

echo "Docker installed: $(docker --version)"
DOCKEREOF

echo ""
echo "============================================"
echo " Phase 4: Configure Docker daemon (TCP API)"
echo "============================================"

# Configure daemon.json for TCP API (Traefik needs this)
ssh "$PVE_AUX" pct exec $CTID -- bash -s <<'DAEMONEOF'
set -euo pipefail

cat > /etc/docker/daemon.json <<'JSON'
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2375"]
}
JSON

mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/override.conf <<'CONF'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock
CONF

systemctl daemon-reload
systemctl restart docker
echo "Docker daemon configured with TCP API on :2375"
DAEMONEOF

echo ""
echo "============================================"
echo " Phase 5: Configure UFW"
echo "============================================"

ssh "$PVE_AUX" pct exec $CTID -- bash -s <<'UFWEOF'
set -euo pipefail
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 2377/tcp
ufw allow 7946/tcp
ufw allow 7946/udp
ufw allow 4789/udp
ufw allow from 192.168.1.15 to any port 2375 proto tcp
ufw --force enable
echo "UFW configured."
UFWEOF

echo ""
echo "============================================"
echo " Phase 6: Initialize Docker Swarm"
echo "============================================"

ssh "$PVE_AUX" pct exec $CTID -- bash -c \
  "docker swarm init --advertise-addr $MGR1_IP"

# Get tokens
MANAGER_TOKEN=$(ssh "$PVE_AUX" pct exec $CTID -- docker swarm join-token -q manager)
WORKER_TOKEN=$(ssh "$PVE_AUX" pct exec $CTID -- docker swarm join-token -q worker)

echo ""
echo "============================================"
echo " Phase 7: Create overlay networks"
echo "============================================"

ssh "$PVE_AUX" pct exec $CTID -- bash -s <<'NETEOF'
docker network create --driver overlay --attachable proxy
docker network create --driver overlay --attachable internal
echo "Created: proxy, internal"
NETEOF

ssh "$PVE_AUX" pct exec $CTID -- mkdir -p /opt/secrets /opt/stacks

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} CT 106 Rebuild Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Manager join token:"
echo "  $MANAGER_TOKEN"
echo ""
echo "Worker join token:"
echo "  $WORKER_TOKEN"
echo ""
echo -e "${YELLOW}NEXT STEPS:${NC}"
echo ""
echo "1. Rejoin Manager 2 (CT 109 on helm):"
echo "   ssh root@192.168.1.77 'pct exec 109 -- docker swarm leave --force'"
echo "   ssh root@192.168.1.77 'pct exec 109 -- docker swarm join --token $MANAGER_TOKEN $MGR1_IP:2377'"
echo ""
echo "2. Rejoin Manager 3 (CT 110 on aux2):"
echo "   ssh root@192.168.1.80 'pct exec 110 -- docker swarm leave --force'"
echo "   ssh root@192.168.1.80 'pct exec 110 -- docker swarm join --token $MANAGER_TOKEN $MGR1_IP:2377'"
echo ""
echo "3. Rejoin workers using: docs/scripts/proxmox/rejoin-swarm-worker.sh <ip>"
echo ""
echo "4. Create secrets: ssh root@$MGR1_IP 'cat > /opt/secrets/swarm.env'"
echo ""
echo "5. Redeploy stacks: docs/scripts/swarm/redeploy-all.sh"
echo ""
echo "6. Restart Traefik: ssh root@192.168.1.15 'cd /opt/traefik && docker compose restart'"
echo ""
