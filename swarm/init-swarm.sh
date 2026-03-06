#!/usr/bin/env bash
set -euo pipefail

# Docker Swarm Multi-Manager Setup
#
# Topology:
#   Managers (LXC containers):
#     CT 106 on aux  (.18) → 192.168.1.23  (primary, Docker API exposed for Traefik)
#     CT 109 on helm (.77) → 192.168.1.26
#     CT 110 on aux2 (.80) → 192.168.1.27
#   Workers (bare-metal Docker on Proxmox hosts / workstation):
#     MSI  host  → 192.168.1.74
#     AI   NUC   → 192.168.1.69
#     Workstation → 192.168.1.95
#
# Standalone (NOT in swarm):
#   Traefik:    CT 102 on aux2, .15
#   Technitium: CT 101 on aux2, .51
#   Audio:      MSI host .74 (docker-compose)
#   Email-RAG:  VM 401 on ai, .110
#
# Prerequisites:
#   - Proxmox hosts aux, helm, aux2 reachable via SSH as root
#   - Ubuntu 24.04 CT template on each host
#   - MSI, AI, workstation have Docker installed
#   - Run from a machine with SSH access to everything

# --- Proxmox hosts (for creating LXC containers) ---
PVE_AUX="root@192.168.1.18"
PVE_HELM="root@192.168.1.77"
PVE_AUX2="root@192.168.1.80"

# --- Manager IPs ---
MGR1_IP="192.168.1.23"   # CT 106 on aux  (primary)
MGR2_IP="192.168.1.26"   # CT 109 on helm
MGR3_IP="192.168.1.27"   # CT 110 on aux2

# --- Worker hosts (bare-metal Docker) ---
WORKER_MSI="root@192.168.1.74"
WORKER_AI="root@192.168.1.69"
WORKER_WS="chris@192.168.1.95"

GATEWAY="192.168.1.1"
ROOT_PASSWORD="Terry87!"
CT_TEMPLATE="local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Helper: create a privileged LXC container with nesting + AppArmor unconfined
# ---------------------------------------------------------------------------
create_ct() {
  local pve_host=$1 ctid=$2 hostname=$3 ip=$4 cores=$5 memory=$6 disk=$7

  echo "==> Creating CT $ctid ($hostname) on $pve_host ..."
  ssh "$pve_host" bash -s <<CTEOF
set -euo pipefail

if pct status $ctid &>/dev/null; then
  echo "CT $ctid already exists, skipping creation"
else
  pct create $ctid $CT_TEMPLATE \\
    --hostname $hostname \\
    --cores $cores \\
    --memory $memory \\
    --rootfs local-lvm:$disk \\
    --net0 name=eth0,bridge=vmbr0,ip=$ip/24,gw=$GATEWAY \\
    --features keyctl=1,nesting=1 \\
    --unprivileged 0 \\
    --password "$ROOT_PASSWORD" \\
    --start 0
fi

# Add AppArmor unconfined if not already set
if ! grep -q 'lxc.apparmor.profile' /etc/pve/lxc/$ctid.conf 2>/dev/null; then
  echo 'lxc.apparmor.profile: unconfined' >> /etc/pve/lxc/$ctid.conf
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
install_docker_lxc() {
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
# Helper: configure UFW for a swarm manager
# ---------------------------------------------------------------------------
configure_ufw_manager() {
  local pve_host=$1 ctid=$2

  echo "==> Configuring UFW on CT $ctid ..."
  ssh "$pve_host" pct exec "$ctid" -- bash -s <<'UFWEOF'
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
UFWEOF
}

# ---------------------------------------------------------------------------
# Phase 1: Manager 1 — CT 106 on aux (primary, existing)
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 1: Manager 1 — CT 106 on aux"
echo "========================================="

create_ct "$PVE_AUX" 106 swarm-manager "$MGR1_IP" 2 2048 20
install_docker_lxc "$PVE_AUX" 106

# Configure Docker daemon with TCP API (for Traefik)
echo "==> Configuring Docker daemon on manager 1 (TCP API) ..."
cat "$SCRIPT_DIR/../lxc/swarm-manager/daemon.json" | \
  ssh "$PVE_AUX" "pct exec 106 -- tee /etc/docker/daemon.json > /dev/null"

ssh "$PVE_AUX" pct exec 106 -- bash -s <<'SVCEOF'
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

# UFW for manager 1 — also allow Traefik to Docker API
configure_ufw_manager "$PVE_AUX" 106
ssh "$PVE_AUX" pct exec 106 -- bash -c \
  "ufw allow from 192.168.1.15 to any port 2375 proto tcp"

# Initialize or verify swarm
echo "==> Initializing Docker Swarm ..."
ssh "$PVE_AUX" pct exec 106 -- bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && echo 'Swarm already initialized' || docker swarm init --advertise-addr $MGR1_IP"

# Get join tokens
MANAGER_TOKEN=$(ssh "$PVE_AUX" pct exec 106 -- docker swarm join-token -q manager)
WORKER_TOKEN=$(ssh "$PVE_AUX" pct exec 106 -- docker swarm join-token -q worker)
echo "==> Manager join token: $MANAGER_TOKEN"
echo "==> Worker join token: $WORKER_TOKEN"

# ---------------------------------------------------------------------------
# Phase 2: Manager 2 — CT 109 on helm
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 2: Manager 2 — CT 109 on helm"
echo "========================================="

create_ct "$PVE_HELM" 109 swarm-manager-2 "$MGR2_IP" 2 2048 20
install_docker_lxc "$PVE_HELM" 109
configure_ufw_manager "$PVE_HELM" 109

echo "==> Joining CT 109 to swarm as manager ..."
ssh "$PVE_HELM" pct exec 109 -- bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && echo 'Already in swarm' || docker swarm join --token $MANAGER_TOKEN $MGR1_IP:2377"

# ---------------------------------------------------------------------------
# Phase 3: Manager 3 — CT 110 on aux2
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 3: Manager 3 — CT 110 on aux2"
echo "========================================="

create_ct "$PVE_AUX2" 110 swarm-manager-3 "$MGR3_IP" 2 2048 20
install_docker_lxc "$PVE_AUX2" 110
configure_ufw_manager "$PVE_AUX2" 110

echo "==> Joining CT 110 to swarm as manager ..."
ssh "$PVE_AUX2" pct exec 110 -- bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && echo 'Already in swarm' || docker swarm join --token $MANAGER_TOKEN $MGR1_IP:2377"

# ---------------------------------------------------------------------------
# Phase 4: Workers (bare-metal Docker on hosts)
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 4: Workers"
echo "========================================="

# --- Worker: MSI (.74) ---
echo "==> Cleaning up orphaned swarm on MSI ..."
ssh "$WORKER_MSI" bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && docker swarm leave --force || true"

echo "==> Joining MSI to swarm as worker ..."
ssh "$WORKER_MSI" bash -c \
  "docker swarm join --token $WORKER_TOKEN $MGR1_IP:2377"

# --- Worker: AI NUC (.69) ---
echo "==> Cleaning up orphaned swarm on AI ..."
ssh "$WORKER_AI" bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && docker swarm leave --force || true"

echo "==> Joining AI to swarm as worker ..."
ssh "$WORKER_AI" bash -c \
  "docker swarm join --token $WORKER_TOKEN $MGR1_IP:2377"

# --- Worker: Workstation (.95) ---
echo "==> Joining workstation to swarm as worker ..."
ssh "$WORKER_WS" bash -c \
  "docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active && docker swarm leave --force 2>/dev/null; \
   sudo docker swarm join --token $WORKER_TOKEN $MGR1_IP:2377"

# ---------------------------------------------------------------------------
# Phase 5: Node labels and overlay networks
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 5: Labels & Networks"
echo "========================================="

echo "==> Adding node labels ..."
ssh "$PVE_AUX" pct exec 106 -- bash -s <<'LBLEOF'
set -euo pipefail
for node in $(docker node ls --format '{{.Hostname}}'); do
  case "$node" in
    msi)              docker node update --label-add host=msi "$node" ;;
    ai)               docker node update --label-add host=ai "$node" ;;
    chris-workstation|chris) docker node update --label-add host=workstation --label-add gpu=true "$node" ;;
    swarm-manager)    docker node update --label-add host=aux "$node" ;;
    swarm-manager-2)  docker node update --label-add host=helm "$node" ;;
    swarm-manager-3)  docker node update --label-add host=aux2 "$node" ;;
  esac
done
LBLEOF

echo "==> Creating overlay networks ..."
ssh "$PVE_AUX" pct exec 106 -- bash -s <<'NETEOF'
set -euo pipefail
docker network ls --format '{{.Name}}' | grep -q '^proxy$'    || docker network create --driver overlay --attachable proxy
docker network ls --format '{{.Name}}' | grep -q '^internal$' || docker network create --driver overlay --attachable internal
NETEOF

# ---------------------------------------------------------------------------
# Phase 6: Volume directories
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Phase 6: Volume Directories"
echo "========================================="

echo "==> Creating directories on manager 1 ..."
ssh "$PVE_AUX" pct exec 106 -- mkdir -p /opt/secrets /opt/stacks

echo "==> Creating directories on manager 2 (helm) ..."
ssh "$PVE_HELM" pct exec 109 -- mkdir -p /opt/infisical/postgres

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo " Verification"
echo "========================================="

echo "==> Swarm nodes:"
ssh "$PVE_AUX" pct exec 106 -- docker node ls

echo ""
echo "==> Overlay networks:"
ssh "$PVE_AUX" pct exec 106 -- docker network ls --filter driver=overlay

echo ""
echo "========================================="
echo " Done! Next steps:"
echo "========================================="
echo ""
echo "1. Verify all 6 nodes are Ready:"
echo "   ssh root@192.168.1.23 docker node ls"
echo ""
echo "2. Deploy stacks:"
echo "   ./deploy-all.sh"
echo ""
echo "3. (Optional) Create Infisical secrets:"
echo "   ssh root@192.168.1.23"
echo "   cat > /opt/secrets/swarm.env <<'EOF'"
echo "   INFISICAL_ENCRYPTION_KEY=<key>"
echo "   INFISICAL_AUTH_SECRET=<secret>"
echo "   INFISICAL_POSTGRES_PASSWORD=<password>"
echo "   EOF"
echo ""
echo "4. Restart Traefik (CT 102, .15) to pick up swarm Docker provider"
echo ""
