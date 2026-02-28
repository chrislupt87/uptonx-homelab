# Infrastructure Changes — 2026-02-28

## Summary
Pivoted from Docker Swarm to HashiCorp Nomad as the orchestration platform.
Set up a 2-node Nomad cluster with LXC server and workstation client.

## Changes Made

### Proxmox (helm — 192.168.1.77)
- Created LXC container CT 100 (already existed, configured it)
  - Hostname: `nomad`
  - IP: 192.168.1.101/24, GW: 192.168.1.1
  - Ubuntu 24.04, unprivileged, nesting enabled
  - 2 cores, 2048MB RAM, 512MB swap, 20GB disk on local-lvm

### LXC (nomad — 192.168.1.101)
- Set root password
- Installed: curl, wget, unzip, gnupg, lsb-release, ca-certificates
- Enabled `PermitRootLogin yes` in `/etc/ssh/sshd_config`
- Copied workstation SSH key to `/root/.ssh/authorized_keys`
- Added HashiCorp apt repo + GPG key
- Installed Nomad 1.11.2 via apt
- Created `/etc/nomad.d/nomad.hcl` — server+client mode, datacenter `uptonx`
- Created `/opt/nomad/data`
- Enabled and started `nomad.service` via systemd

### Workstation (192.168.1.95)
- Downloaded Nomad 1.11.2 binary to `/usr/local/bin/nomad`
- Created `/etc/nomad.d/nomad.hcl` — client-only mode, GPU meta `amd-rx7600`
- Created `/opt/nomad/data`
- Created `/etc/systemd/system/nomad.service` (custom unit file)
- Enabled and started `nomad.service` via systemd

### Repo (~/uptonx-homelab)
- Added `nomad/configs/lxc-server.hcl`
- Added `nomad/configs/workstation-client.hcl`
- Created `CONTEXT.md` with current infrastructure state
- Created `SESSION.md` with session log
- Created this file (`INFRA-CHANGES.md`)

## Ports / Services Exposed
- Nomad HTTP API/UI: 192.168.1.101:4646
- Nomad RPC: 192.168.1.101:4647
- Nomad Serf: 192.168.1.101:4648

## Credentials
- LXC root password was set to `uptonx2024` (change this)

---

# Infrastructure Changes — 2026-02-28 (Session 2)

## Summary
Deployed Technitium DNS and Traefik v3 reverse proxy as standalone Docker containers in dedicated LXCs on Proxmox.

## Changes Made

### Proxmox (helm — 192.168.1.77)
- Created LXC container CT 101
  - Hostname: `technitium`
  - IP: 192.168.1.51/24, GW: 192.168.1.1
  - Ubuntu 24.04, unprivileged, nesting+keyctl enabled
  - 1 core, 512MB RAM, 256MB swap, 8GB disk on local-lvm
- Created LXC container CT 102
  - Hostname: `traefik`
  - IP: 192.168.1.15/24, GW: 192.168.1.1
  - Ubuntu 24.04, unprivileged, nesting+keyctl enabled
  - 1 core, 512MB RAM, 256MB swap, 8GB disk on local-lvm

### Technitium LXC (CT 101 — 192.168.1.51)
- Copied workstation SSH key, enabled root login
- Disabled `systemd-resolved` (frees port 53)
- Installed Docker CE 29.2.1 + docker-compose-plugin
- Deployed Technitium DNS via Docker Compose (`/opt/technitium/`)
- Created `uptonx.local` primary zone with A records:
  - helm (192.168.1.77), nomad (192.168.1.101), technitium (192.168.1.51)
  - traefik (192.168.1.15), workstation (192.168.1.95), pbs (192.168.1.19)
  - nas (192.168.1.11), aux (192.168.1.18), aux2 (192.168.1.80)
  - ai (192.168.1.69), msi (192.168.1.74)
- Created `uptonx.com` primary zone (split-horizon) with wildcard `*.uptonx.com` → 192.168.1.15
- Set upstream forwarders: 1.1.1.1, 1.0.0.1

### Traefik LXC (CT 102 — 192.168.1.15)
- Copied workstation SSH key, enabled root login
- Installed Docker CE 29.2.1 + docker-compose-plugin
- Deployed Traefik v3.3.7 via Docker Compose (`/opt/traefik/`)
- Configured Cloudflare DNS challenge for Let's Encrypt (wildcard `*.uptonx.com`)
- File provider for routing (no Docker socket)
- Initial routes: nomad.uptonx.com, dns.uptonx.com, traefik.uptonx.com
- Cloudflare API token stored in `/opt/traefik/.env` (not in repo)

### Repo (~/uptonx-homelab)
- Added `lxc/technitium/docker-compose.yml`
- Added `lxc/traefik/docker-compose.yml`
- Added `lxc/traefik/traefik.yml`
- Added `lxc/traefik/dynamic/routers.yml`
- Updated `CONTEXT.md` with new containers and services
- Updated this file (`INFRA-CHANGES.md`)

## Ports / Services Exposed
- Technitium DNS: 192.168.1.51:53 (TCP/UDP), 192.168.1.51:5380 (Web UI)
- Traefik: 192.168.1.15:80 (HTTP→HTTPS redirect), 192.168.1.15:443 (HTTPS), 192.168.1.15:8080 (Dashboard)

## Credentials
- Technitium admin: admin/admin (change this)
- Cloudflare API token in `/opt/traefik/.env` on CT 102
