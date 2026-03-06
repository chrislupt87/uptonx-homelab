#!/usr/bin/env bash
set -euo pipefail

# Docker Swarm Full Architecture Setup
# Creates CT 106 (manager on aux), CT 107 (worker on helm), CT 108 (worker on msi)
# Initializes Swarm, joins workers, creates overlay networks, and prepares
# volume directories and config files for all services.
#
# Prerequisites:
#   - Proxmox hosts aux (.18), helm (.77), msi (.74) reachable via SSH as root
#   - Ubuntu 24.04 CT template downloaded on each host
#   - This script is run from a machine with SSH access to all Proxmox hosts
#
# After running this, use deploy-all.sh to deploy stacks.

MANAGER_HOST="root@192.168.1.18"   # aux
WORKER1_HOST="root@192.168.1.77"   # helm
WORKER2_HOST="root@192.168.1.74"   # msi

MANAGER_IP="192.168.1.23"
WORKER1_IP="192.168.1.24"
WORKER2_IP="192.168.1.25"
GATEWAY="192.168.1.1"

ROOT_PASSWORD="Terry87!"
CT_TEMPLATE="local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Helper: create a privileged LXC container with nesting
# ---------------------------------------------------------------------------
create_ct() {
  local pve_host=$1 ctid=$2 hostname=$3 ip=$4 cores=$5 memory=$6 disk=$7

  echo "==> Creating CT $ctid ($hostname) on $pve_host ..."
  ssh "$pve_host" bash -s <<CTEOF
set -euo pipefail

# Skip if container already exists
if pct status $ctid &>/dev/null; then
  echo "CT $ctid already exists, skipping creation"
else
  pct create $ctid $CT_TEMPLATE \\
    --hostname $hostname \\
    --cores $cores \\
    --memory $memory \\
    --rootfs local-lvm:$disk \\
    --net0 name=eth0,bridge=vmbr0,ip=$ip/24,gw=$GATEWAY \\
    --features nesting=1 \\
    --unprivileged 0 \\
    --password "$ROOT_PASSWORD" \\
    --start 0
fi

# Start if not running
if ! pct status $ctid | grep -q running; then
  pct start $ctid
  sleep 5
fi
CTEOF
}

# ---------------------------------------------------------------------------
# Helper: install Docker CE inside an LXC container
# ---------------------------------------------------------------------------
install_docker() {
  local pve_host=$1 ctid=$2

  echo "==> Installing Docker in CT $ctid ..."
  ssh "$pve_host" pct exec "$ctid" -- bash -s <<'DKEOF'
set -euo pipefail

# Enable root SSH login
sed -i 's/#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
systemctl restart sshd || true

if command -v docker &>/dev/null; then
  echo "Docker already installed, skipping"
  exit 0
fi

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
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
DKEOF
}

# ---------------------------------------------------------------------------
# Phase 1: Create manager (CT 106 on aux)
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 1: Swarm Manager (CT 106 on aux)"
echo "========================================="

create_ct "$MANAGER_HOST" 106 swarm-manager "$MANAGER_IP" 2 2048 20

install_docker "$MANAGER_HOST" 106

# Copy daemon.json to expose Docker API
echo "==> Configuring Docker daemon on manager ..."
ssh "$MANAGER_HOST" pct push 106 "$SCRIPT_DIR/../lxc/swarm-manager/daemon.json" /etc/docker/daemon.json 2>/dev/null || \
  cat "$SCRIPT_DIR/../lxc/swarm-manager/daemon.json" | ssh "$MANAGER_HOST" "pct exec 106 -- tee /etc/docker/daemon.json > /dev/null"

# Override systemd docker.service to remove -H fd:// (conflicts with daemon.json hosts)
ssh "$MANAGER_HOST" pct exec 106 -- bash -s <<'SVCEOF'
set -euo pipefail
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/override.conf <<'CONF'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock
CONF
systemctl daemon-reload
systemctl restart docker
SVCEOF

# Configure UFW on manager
echo "==> Configuring UFW on manager ..."
ssh "$MANAGER_HOST" pct exec 106 -- bash -s <<'UFWEOF'
set -euo pipefail
if ! command -v ufw &>/dev/null; then
  apt-get install -y -qq ufw
fi
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                          # SSH
ufw allow from 192.168.1.15 to any port 2375 proto tcp  # Traefik
ufw allow from 192.168.1.21 to any port 2375 proto tcp  # Portainer (legacy)
ufw allow 2377/tcp                        # Swarm cluster management
ufw allow 7946/tcp                        # Swarm node communication
ufw allow 7946/udp                        # Swarm node communication
ufw allow 4789/udp                        # Swarm overlay network (VXLAN)
ufw --force enable
UFWEOF

# Initialize Swarm
echo "==> Initializing Docker Swarm ..."
ssh "$MANAGER_HOST" pct exec 106 -- bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && echo 'Swarm already initialized' || docker swarm init --advertise-addr $MANAGER_IP"

# Get join token
WORKER_TOKEN=$(ssh "$MANAGER_HOST" pct exec 106 -- docker swarm join-token -q worker)
echo "==> Worker join token: $WORKER_TOKEN"

# ---------------------------------------------------------------------------
# Phase 2: Create workers (CT 107 on helm, CT 108 on msi)
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 2: Swarm Workers"
echo "========================================="

# --- Worker 1: CT 107 on helm ---
create_ct "$WORKER1_HOST" 107 swarm-worker-1 "$WORKER1_IP" 2 2048 20
install_docker "$WORKER1_HOST" 107

echo "==> Joining CT 107 to swarm ..."
ssh "$WORKER1_HOST" pct exec 107 -- bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && echo 'Already in swarm' || docker swarm join --token $WORKER_TOKEN $MANAGER_IP:2377"

# Open swarm ports + Gitea SSH on worker 1
ssh "$WORKER1_HOST" pct exec 107 -- bash -s <<'WUFWEOF'
set -euo pipefail
if ! command -v ufw &>/dev/null; then
  apt-get install -y -qq ufw
fi
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                          # SSH
ufw allow 222/tcp                         # Gitea SSH
ufw allow 2377/tcp                        # Swarm cluster management
ufw allow 7946/tcp                        # Swarm node communication
ufw allow 7946/udp                        # Swarm node communication
ufw allow 4789/udp                        # Swarm overlay network (VXLAN)
ufw --force enable
WUFWEOF

# --- Worker 2: CT 108 on msi ---
create_ct "$WORKER2_HOST" 108 swarm-worker-2 "$WORKER2_IP" 2 2048 20
install_docker "$WORKER2_HOST" 108

echo "==> Joining CT 108 to swarm ..."
ssh "$WORKER2_HOST" pct exec 108 -- bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && echo 'Already in swarm' || docker swarm join --token $WORKER_TOKEN $MANAGER_IP:2377"

# Open swarm ports on worker 2
ssh "$WORKER2_HOST" pct exec 108 -- bash -s <<'WUFWEOF'
set -euo pipefail
if ! command -v ufw &>/dev/null; then
  apt-get install -y -qq ufw
fi
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                          # SSH
ufw allow 2377/tcp                        # Swarm cluster management
ufw allow 7946/tcp                        # Swarm node communication
ufw allow 7946/udp                        # Swarm node communication
ufw allow 4789/udp                        # Swarm overlay network (VXLAN)
ufw --force enable
WUFWEOF

# ---------------------------------------------------------------------------
# Phase 3: Node labels and overlay networks
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 3: Labels & Networks"
echo "========================================="

echo "==> Adding node labels ..."
ssh "$MANAGER_HOST" pct exec 106 -- bash -s <<'LBLEOF'
set -euo pipefail
for node in $(docker node ls --format '{{.Hostname}}'); do
  case "$node" in
    swarm-worker-1) docker node update --label-add host=helm "$node" ;;
    swarm-worker-2) docker node update --label-add host=msi "$node" ;;
  esac
done
LBLEOF

echo "==> Creating overlay networks ..."
ssh "$MANAGER_HOST" pct exec 106 -- bash -s <<'NETEOF'
set -euo pipefail
docker network ls --format '{{.Name}}' | grep -q '^proxy$'    || docker network create --driver overlay --attachable proxy
docker network ls --format '{{.Name}}' | grep -q '^internal$' || docker network create --driver overlay --attachable internal
NETEOF

# ---------------------------------------------------------------------------
# Phase 4: Prepare volume directories and config files
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 4: Volume Dirs & Config"
echo "========================================="

# Manager: stacks and secrets directories
echo "==> Creating directories on manager ..."
ssh "$MANAGER_HOST" pct exec 106 -- bash -s <<'VOLEOF'
mkdir -p /opt/secrets /opt/stacks
VOLEOF

# Worker 1 (helm): Gitea data, Infisical postgres
echo "==> Creating volume directories on worker 1 (helm) ..."
ssh "$WORKER1_HOST" pct exec 107 -- bash -s <<'VOLEOF'
mkdir -p /opt/gitea/data /opt/infisical/postgres
VOLEOF

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Verification"
echo "========================================="

echo "==> Swarm nodes:"
ssh "$MANAGER_HOST" pct exec 106 -- docker node ls

echo ""
echo "==> Overlay networks:"
ssh "$MANAGER_HOST" pct exec 106 -- docker network ls --filter driver=overlay

echo ""
echo "========================================="
echo " Done! Next steps:"
echo "========================================="
echo ""
echo "1. Create secrets file on manager:"
echo "   ssh root@192.168.1.23"
echo "   cat > /opt/secrets/swarm.env <<'EOF'"
echo "   INFISICAL_ENCRYPTION_KEY=<your-encryption-key>"
echo "   INFISICAL_AUTH_SECRET=<your-auth-secret>"
echo "   INFISICAL_POSTGRES_PASSWORD=<your-postgres-password>"
echo "   EOF"
echo ""
echo "2. Restart Traefik (CT 102, .15) to pick up swarm Docker provider"
echo ""
echo "3. Deploy all stacks:"
echo "   ./deploy-all.sh"
echo ""
