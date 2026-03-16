#!/usr/bin/env bash
# ============================================================
# Tailscale VPN Mesh Setup
#
# Strategy: Install Tailscale on ONE node as a subnet router
# to expose the entire 192.168.1.0/24 + 192.168.40.0/24 (cameras).
# This gives remote access to everything without installing
# Tailscale on every host.
#
# Best candidate: aux2 (.80) — it's the network hub (Traefik, DNS)
# and is always on.
#
# Additional: Install on workstation for direct mesh when at home
# + remote access when traveling.
#
# Prerequisites:
#   1. Create Tailscale account: https://tailscale.com
#   2. Install Tailscale app on phone/laptop for remote access
#
# Usage:
#   bash setup-tailscale.sh subnet-router   # Run on aux2
#   bash setup-tailscale.sh workstation      # Run on workstation
#   bash setup-tailscale.sh exit-node        # Run on aux2 (optional, route all traffic)
# ============================================================
set -euo pipefail

MODE="${1:-}"

install_tailscale() {
  if command -v tailscale &>/dev/null; then
    echo "Tailscale already installed: $(tailscale version)"
    return
  fi
  echo "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
}

case "$MODE" in
  subnet-router)
    # ============================================================
    # SUBNET ROUTER — run on aux2 (.80)
    # Advertises the entire LAN + camera VLAN to Tailscale network
    # ============================================================
    echo "=== Setting up Tailscale subnet router ==="
    install_tailscale

    # Enable IP forwarding (required for subnet routing)
    echo 'net.ipv4.ip_forward = 1' | sudo tee /etc/sysctl.d/99-tailscale.conf
    echo 'net.ipv6.conf.all.forwarding = 1' | sudo tee -a /etc/sysctl.d/99-tailscale.conf
    sudo sysctl -p /etc/sysctl.d/99-tailscale.conf

    # Start Tailscale as subnet router
    sudo tailscale up \
      --advertise-routes=192.168.1.0/24,192.168.40.0/24 \
      --accept-dns=false \
      --hostname=homelab-router

    echo ""
    echo "=== Subnet router started ==="
    echo ""
    echo "IMPORTANT: You must approve the subnet routes in Tailscale admin console:"
    echo "  1. Go to https://login.tailscale.com/admin/machines"
    echo "  2. Find 'homelab-router'"
    echo "  3. Click ••• → Edit route settings"
    echo "  4. Enable both subnets: 192.168.1.0/24 and 192.168.40.0/24"
    echo ""
    echo "After approval, any Tailscale device can reach:"
    echo "  - All homelab services (192.168.1.x)"
    echo "  - Camera VLAN (192.168.40.x)"
    echo "  - Traefik UI: https://traefik.uptonx.com"
    echo "  - Frigate: https://frigate.uptonx.com"
    echo "  - etc."
    ;;

  workstation)
    # ============================================================
    # WORKSTATION — join the tailnet
    # ============================================================
    echo "=== Setting up Tailscale on workstation ==="
    install_tailscale

    sudo tailscale up \
      --accept-routes \
      --hostname=workstation

    echo ""
    echo "=== Workstation joined tailnet ==="
    tailscale status
    ;;

  exit-node)
    # ============================================================
    # EXIT NODE — route ALL traffic through homelab (optional)
    # Run on aux2 after subnet-router is already set up
    # ============================================================
    echo "=== Enabling exit node on subnet router ==="

    sudo tailscale up \
      --advertise-routes=192.168.1.0/24,192.168.40.0/24 \
      --advertise-exit-node \
      --accept-dns=false \
      --hostname=homelab-router

    echo ""
    echo "Exit node enabled. Approve in Tailscale admin console."
    echo "Clients can then route ALL internet traffic through your homelab."
    ;;

  *)
    echo "Usage: $0 {subnet-router|workstation|exit-node}"
    echo ""
    echo "  subnet-router  — Run on aux2 (.80). Exposes LAN + camera VLAN."
    echo "  workstation     — Run on workstation (.95). Joins tailnet."
    echo "  exit-node       — Run on aux2 (.80). Also acts as VPN exit node."
    exit 1
    ;;
esac
