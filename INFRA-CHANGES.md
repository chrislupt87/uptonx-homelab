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
