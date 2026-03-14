#!/usr/bin/env bash
set -euo pipefail

# Restore correct AppArmor/nesting LXC config to Swarm manager containers
#
# Usage: ./restore-lxc-config.sh [ctid]
# Without args: fixes all three manager CTs (106, 109, 110)
# With arg:     fixes only the specified CT

ROOT_PASSWORD="Terry87!"

declare -A CT_HOST_MAP=(
  [106]="root@192.168.1.18"   # aux
  [109]="root@192.168.1.77"   # helm
  [110]="root@192.168.1.80"   # aux2
)

fix_ct() {
  local ctid=$1
  local pve_host=${CT_HOST_MAP[$ctid]}

  echo "============================================"
  echo " Fixing CT $ctid on $pve_host"
  echo "============================================"

  # Step 1: Ensure nesting and keyctl features
  echo "[1/4] Checking features ..."
  ssh "$pve_host" bash -s <<FIXEOF
set -euo pipefail
CONF="/etc/pve/lxc/${ctid}.conf"

if ! grep -q 'features:.*nesting=1' "\$CONF" 2>/dev/null; then
  echo "  Adding nesting feature ..."
  if grep -q '^features:' "\$CONF"; then
    sed -i 's/^features:.*/features: keyctl=1,nesting=1/' "\$CONF"
  else
    echo 'features: keyctl=1,nesting=1' >> "\$CONF"
  fi
fi

# Step 2: AppArmor unconfined
echo "[2/4] Checking AppArmor profile ..."
if ! grep -q 'lxc.apparmor.profile: unconfined' "\$CONF" 2>/dev/null; then
  echo "  Adding apparmor unconfined ..."
  echo 'lxc.apparmor.profile: unconfined' >> "\$CONF"
fi

# Step 3: Ensure unprivileged=0
echo "[3/4] Checking privilege level ..."
if grep -q 'unprivileged: 1' "\$CONF" 2>/dev/null; then
  echo "  Changing to privileged ..."
  sed -i 's/unprivileged: 1/unprivileged: 0/' "\$CONF"
fi

echo "[4/4] Current config:"
grep -E 'features|apparmor|unprivileged' "\$CONF" || true
FIXEOF

  echo ""
  echo "  If CT was modified, restart it:"
  echo "    ssh $pve_host 'pct stop $ctid && pct start $ctid'"
  echo ""
}

if [ $# -eq 1 ]; then
  CTID="$1"
  if [ -z "${CT_HOST_MAP[$CTID]+x}" ]; then
    echo "ERROR: Unknown CT $CTID. Valid: 106, 109, 110"
    exit 1
  fi
  fix_ct "$CTID"
else
  for ctid in 106 109 110; do
    fix_ct "$ctid"
  done
fi

echo "============================================"
echo " Done! Remember to restart modified CTs."
echo "============================================"
