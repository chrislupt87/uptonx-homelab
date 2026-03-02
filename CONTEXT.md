# UptonX Homelab — Infrastructure

## Network

- **Subnet**: 192.168.1.0/24
- **Gateway**: 192.168.1.1
- **Internal domain**: uptonx.local (Technitium DNS)
- **External domain**: uptonx.com (Cloudflare)

## Hosts

### helm — Proxmox Hypervisor

| | |
|---|---|
| **IP** | 192.168.1.77 |
| **OS** | Proxmox VE |
| **CPU** | AMD Ryzen 7 5825U |
| **RAM** | 28 GB |
| **SSH** | root@192.168.1.77 |
| **Role** | Hypervisor — runs LXCs (CT 100–102) |

### uptonx-workstation

| | |
|---|---|
| **IP** | 192.168.1.95 |
| **OS** | Kubuntu |
| **CPU** | AMD Ryzen 7 7700X (8-core) |
| **RAM** | 64 GB |
| **GPU** | AMD Radeon RX 7600 |
| **SSH** | chris@192.168.1.95 (localhost) |
| **Role** | Primary workstation, Nomad client |
| **Nomad** | Client, meta: node.type=workstation, node.gpu=amd-rx7600 |

### aux — Proxmox Hypervisor

| | |
|---|---|
| **IP** | 192.168.1.18 |
| **OS** | Proxmox VE (Debian 13 trixie, PVE kernel) |
| **CPU** | AMD Ryzen 7 8845HS |
| **RAM** | 64 GB |
| **SSH** | root@192.168.1.18 |
| **Role** | Proxmox host — runs LXC (CT 104) |

### aux2 — Proxmox Hypervisor

| | |
|---|---|
| **IP** | 192.168.1.80 |
| **OS** | Proxmox VE (Debian 13 trixie, PVE kernel) |
| **CPU** | Intel N150 |
| **RAM** | 16 GB |
| **Disk** | 94 GB |
| **SSH** | root@192.168.1.80 |
| **Role** | Proxmox host — runs LXC (CT 103) |

### ai (NUC) — Proxmox Hypervisor

| | |
|---|---|
| **IP** | 192.168.1.69 |
| **OS** | Proxmox VE (Debian 13 trixie, PVE kernel) |
| **CPU** | 13th Gen Intel Core i5-1340P |
| **RAM** | 64 GB |
| **SSH** | root@192.168.1.69 |
| **Role** | Proxmox host — runs LXC (CT 301) |

### msi — Proxmox Hypervisor

| | |
|---|---|
| **IP** | 192.168.1.74 |
| **OS** | Proxmox VE (Debian 13 trixie, PVE kernel) |
| **CPU** | Intel Core Ultra 7 155H |
| **RAM** | 32 GB |
| **SSH** | root@192.168.1.74 |
| **Role** | Proxmox host — runs LXC (CT 105) |

### nas (UGreen)

| | |
|---|---|
| **IP** | 192.168.1.11 |
| **Hostname** | CLU-NAS |
| **SSH** | chris-admin@192.168.1.11 |
| **Role** | Network-attached storage |

### pbs — Proxmox Backup Server

| | |
|---|---|
| **IP** | 192.168.1.19 |
| **SSH** | root@192.168.1.19 |
| **Role** | Proxmox Backup Server only (not part of Nomad cluster) |

## Proxmox LXCs

### On helm (192.168.1.77)

| CT ID | Hostname | IP | Role | Status |
|-------|----------|----|------|--------|
| 100 | nomad | 192.168.1.101 | Nomad server + client (privileged) | Running |
| 101 | technitium | 192.168.1.51 | DNS server (Docker) | Running |
| 102 | traefik | 192.168.1.15 | Reverse proxy (Docker) | Running |

### On aux2 (192.168.1.80)

| CT ID | Hostname | IP | Role | Status |
|-------|----------|----|------|--------|
| 103 | nomad2 | 192.168.1.102 | Nomad server + client (privileged) | Running |

### On aux (192.168.1.18)

| CT ID | Hostname | IP | Role | Status |
|-------|----------|----|------|--------|
| 104 | nomad3 | 192.168.1.104 | Nomad server + client (privileged) | Running |

### On ai (192.168.1.69)

| CT ID | Hostname | IP | Role | Status |
|-------|----------|----|------|--------|
| 301 | nomad-ai | 192.168.1.103 | Nomad client (privileged) | Running |

### On msi (192.168.1.74)

| CT ID | Hostname | IP | Role | Status |
|-------|----------|----|------|--------|
| 105 | nomad-msi | 192.168.1.105 | Nomad client (privileged) | Running |

## Nomad Cluster

- **Version**: 1.11.2
- **Datacenter**: uptonx
- **Region**: global
- **UI**: http://192.168.1.101:4646
- **Configs**: `nomad/configs/`

| Node | IP | Role | Status |
|------|----|------|--------|
| nomad (CT 100) | 192.168.1.101 | Server + client | Ready |
| nomad2 (CT 103) | 192.168.1.102 | Server + client | Ready |
| nomad3 (CT 104) | 192.168.1.104 | Server + client | Ready |
| nomad-ai (CT 301) | 192.168.1.103 | Client | Ready |
| nomad-msi (CT 105) | 192.168.1.105 | Client | Ready |
| uptonx-workstation | 192.168.1.95 | Client | Ready |

## Services

### Managed by Nomad

| Job | Type | Description |
|-----|------|-------------|
| nfs-csi-controller | service (count=1) | NFS CSI controller plugin |
| nfs-csi-nodes | system (all nodes) | NFS CSI node plugin (privileged) |

### Standalone (Docker on LXCs)

| Service | Host | Access | Notes |
|---------|------|--------|-------|
| Technitium DNS | CT 101 (192.168.1.51) | http://192.168.1.51:5380, port 53 | Zones: uptonx.local, uptonx.com |
| Traefik v3 | CT 102 (192.168.1.15) | http://192.168.1.15:8080, ports 80/443 | Cloudflare DNS challenge, wildcard *.uptonx.com |

### Standalone (Docker on bare metal)

_None — AI NUC services cleared, to be redeployed as Nomad jobs._

## Storage (NFS CSI)

- **NAS**: 192.168.1.11 (`chris-admin`), export: `/volume1/UptonX`
- **CSI Plugin**: `nfs` (registry.k8s.io/sig-storage/nfsplugin:v4.13.1)
- **Protocol**: NFSv3 (UGreen NAS doesn't support NFSv4 properly)
- **Jobs**: `nomad/jobs/nfs-csi-controller.nomad.hcl`, `nomad/jobs/nfs-csi-nodes.nomad.hcl`
- **Volume definitions**: `nomad/volumes/*.volume.hcl`

### Registered Volumes

| Volume ID | NAS Path | Notes |
|-----------|----------|-------|
| test-data | /volume1/UptonX/test | Test volume for verification |

### Adding a new volume

1. Create `nomad/volumes/<name>.volume.hcl` (copy from test-data template)
2. Create the directory on the NAS: `ssh chris-admin@192.168.1.11 "mkdir -p /volume1/UptonX/<name>"`
3. Register: `nomad volume register nomad/volumes/<name>.volume.hcl`

### LXC Requirements

Nomad LXCs (CT 100, 103) must be **privileged** (`unprivileged: 0`) with `lxc.apparmor.profile: unconfined` and `features: mount=nfs,nesting=1` to support NFS mounts inside Docker containers.

## Traefik Routes

| Route | Target |
|-------|--------|
| nomad.uptonx.com | 192.168.1.101:4646 |
| dns.uptonx.com | 192.168.1.51:5380 |
| traefik.uptonx.com | 192.168.1.15:8080 |
