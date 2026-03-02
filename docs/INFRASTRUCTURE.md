# UptonX Homelab Infrastructure

## Overview

The UptonX homelab is a distributed compute cluster built across 5 physical machines and a workstation, all on a flat 192.168.1.0/24 network. The cluster uses **HashiCorp Nomad** for workload orchestration, **Consul** for service discovery, **Technitium DNS** for internal/external name resolution, and **Traefik** as a reverse proxy for HTTPS ingress. Shared storage is provided by a UGreen NAS over NFS, surfaced to Nomad via a CSI plugin.

```
                        ┌─────────────────────────────────────────┐
                        │          192.168.1.0/24 Network         │
                        └─────────────────────────────────────────┘
                                          │
           ┌──────────────────────────────┼──────────────────────────────┐
           │                              │                              │
    ┌──────┴──────┐                ┌──────┴──────┐                ┌──────┴──────┐
    │    helm     │                │    aux2     │                │     aux     │
    │ .77 Proxmox │                │ .80 Proxmox │                │ .18 Proxmox │
    │  Ryzen 7    │                │  Intel N150 │                │  Ryzen 7    │
    │   28 GB     │                │   16 GB     │                │   64 GB     │
    ├─────────────┤                ├─────────────┤                ├─────────────┤
    │ CT100 nomad │                │CT103 nomad2 │                │CT104 nomad3 │
    │ .101 Server │                │ .102 Server │                │ .104 Server │
    ├─────────────┤                └─────────────┘                └─────────────┘
    │CT101 dns    │
    │ .51         │
    ├─────────────┤         ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
    │CT102 traefik│         │   ai (NUC)  │    │     msi     │    │ workstation │
    │ .15         │         │ .69 Proxmox │    │ .74 Proxmox │    │    .95      │
    └─────────────┘         │  i5-1340P   │    │ Ultra 7 155H│    │ Ryzen 7    │
                            │   64 GB     │    │   32 GB     │    │  7700X     │
                            ├─────────────┤    ├─────────────┤    │   64 GB    │
                            │CT301 nom-ai │    │CT105 nom-msi│    │ RX 7600 GPU│
                            │ .103 Client │    │ .105 Client │    │   Client   │
                            └─────────────┘    └─────────────┘    └─────────────┘

                            ┌─────────────┐    ┌─────────────┐
                            │  NAS (UGreen)│    │     PBS     │
                            │    .11      │    │    .19      │
                            │  NFS Storage│    │   Backups   │
                            └─────────────┘    └─────────────┘
```

---

## Physical Hosts

| Name | IP | CPU | RAM | OS | Role |
|------|----|-----|-----|----|------|
| helm | 192.168.1.77 | AMD Ryzen 7 5825U | 28 GB | Proxmox VE | Hypervisor — CT 100, 101, 102 |
| aux2 | 192.168.1.80 | Intel N150 | 16 GB | Proxmox VE | Hypervisor — CT 103 |
| aux | 192.168.1.18 | AMD Ryzen 7 8845HS | 64 GB | Proxmox VE | Hypervisor — CT 104 |
| ai (NUC) | 192.168.1.69 | Intel i5-1340P | 64 GB | Proxmox VE | Hypervisor — CT 301 |
| msi | 192.168.1.74 | Intel Core Ultra 7 155H | 32 GB | Proxmox VE | Hypervisor — CT 105 |
| workstation | 192.168.1.95 | AMD Ryzen 7 7700X | 64 GB | Kubuntu | Desktop + Nomad client |
| NAS | 192.168.1.11 | — | — | UGreen OS | Network-attached storage |
| PBS | 192.168.1.19 | — | — | Proxmox BS | Backup server (not in cluster) |

---

## Network & DNS

| Setting | Value |
|---------|-------|
| Subnet | 192.168.1.0/24 |
| Gateway | 192.168.1.1 |
| Internal domain | uptonx.local |
| External domain | uptonx.com |
| DNS server | Technitium (192.168.1.51) |
| Forwarders | 1.1.1.1, 1.0.0.1 |

**Technitium DNS** runs on CT 101 (`192.168.1.51`) as a Docker container on the `helm` hypervisor. It serves two zones:

- **uptonx.local** — A records for all internal hosts and LXCs
- **uptonx.com** — Split-horizon: internal requests resolve to Traefik (192.168.1.15), external requests go to Cloudflare

Web UI: http://192.168.1.51:5380

---

## LXC Containers

All Nomad LXCs are **privileged** (`unprivileged: 0`) with `lxc.apparmor.profile: unconfined` and `features: mount=nfs,nesting=1`. This is required for Docker and NFS mounts to work inside the containers.

| CT ID | Hostname | IP | Proxmox Host | Role |
|-------|----------|----|--------------|------|
| 100 | nomad | 192.168.1.101 | helm (.77) | Nomad server + client |
| 101 | technitium | 192.168.1.51 | helm (.77) | DNS server (Docker) |
| 102 | traefik | 192.168.1.15 | helm (.77) | Reverse proxy (Docker) |
| 103 | nomad2 | 192.168.1.102 | aux2 (.80) | Nomad server + client |
| 104 | nomad3 | 192.168.1.104 | aux (.18) | Nomad server + client |
| 301 | nomad-ai | 192.168.1.103 | ai (.69) | Nomad client |
| 105 | nomad-msi | 192.168.1.105 | msi (.74) | Nomad client |

**Standard LXC setup**: Debian 12, root password `Terry87!`, root SSH enabled, Docker + nfs-common installed, Nomad + Consul binaries at `/usr/local/bin/`.

---

## Nomad Cluster

| | |
|---|---|
| **Version** | 1.11.2 |
| **Datacenter** | uptonx |
| **Region** | global |
| **UI** | http://192.168.1.101:4646 or https://nomad.uptonx.com |
| **Bootstrap** | 3 servers (quorum requires 2) |

### Topology

```
         Nomad Servers (Raft consensus)                Nomad Clients (workloads)
    ┌──────────────────────────────────┐         ┌──────────────────────────────┐
    │  nomad    .101  (CT 100, helm)   │         │  nomad-ai  .103  (CT 301)   │
    │  nomad2   .102  (CT 103, aux2)   │ ◄─────► │  nomad-msi .105  (CT 105)   │
    │  nomad3   .104  (CT 104, aux)    │         │  workstation .95  (bare)     │
    └──────────────────────────────────┘         └──────────────────────────────┘
```

The 3 server nodes also run as clients (they accept workloads too), giving 6 total nodes in the cluster. Servers use Raft for leader election and state replication. Clients register with all 3 servers for redundancy.

### Node Metadata

| Node | node.type | node.gpu | Notes |
|------|-----------|----------|-------|
| nomad (CT 100) | server-lxc | — | Server + client |
| nomad2 (CT 103) | server-lxc | — | Server + client |
| nomad3 (CT 104) | server-lxc | — | Server + client |
| nomad-ai (CT 301) | ai-nuc | — | 800 GB /data host volume |
| nomad-msi (CT 105) | client-lxc | — | |
| workstation | workstation | amd-rx7600 | Only GPU node |

### Nomad Drivers

All nodes have:
- **docker** — privileged containers allowed, volume mounts enabled
- **raw_exec** — enabled for running binaries directly

### Configuration Files

Stored in `nomad/configs/` in the repo:

| File | Node | Role |
|------|------|------|
| lxc-server.hcl | nomad (CT 100) | Server |
| aux2-server.hcl | nomad2 (CT 103) | Server |
| aux-server.hcl | nomad3 (CT 104) | Server |
| ai-nuc-client.hcl | nomad-ai (CT 301) | Client |
| msi-client.hcl | nomad-msi (CT 105) | Client |
| workstation-client.hcl | workstation | Client |

Configs live on nodes at `/etc/nomad.d/nomad.hcl`.

---

## Consul (Service Discovery)

| | |
|---|---|
| **Version** | 1.22.5 |
| **Datacenter** | uptonx |
| **UI** | http://192.168.1.101:8500 |
| **Gossip key** | Encrypted (shared across all nodes) |

### Topology

Consul mirrors the Nomad topology:
- **3 servers** on the same LXCs as the Nomad servers (CT 100, 103, 104)
- **3 clients** on the Nomad client nodes (CT 301, CT 105, workstation)

Consul provides service discovery so Nomad jobs can find each other by name instead of hardcoded IPs. Nomad is being wired to register services with Consul automatically.

Configs live on nodes at `/etc/consul.d/consul.hcl`, systemd service at `consul.service`.

---

## Reverse Proxy (Traefik v3)

Traefik runs on CT 102 (`192.168.1.15`) as a Docker container. It handles HTTPS termination using Cloudflare DNS challenge for wildcard `*.uptonx.com` certificates.

| | |
|---|---|
| **Dashboard** | http://192.168.1.15:8080 or https://traefik.uptonx.com |
| **Ports** | 80 (HTTP → redirect), 443 (HTTPS), 8080 (dashboard) |
| **TLS** | Let's Encrypt via Cloudflare DNS challenge |
| **Config** | File provider, `lxc/traefik/` in repo |

### Current Routes

| External URL | Backend Target |
|---|---|
| https://nomad.uptonx.com | 192.168.1.101:4646 (Nomad UI) |
| https://dns.uptonx.com | 192.168.1.51:5380 (Technitium UI) |
| https://traefik.uptonx.com | 192.168.1.15:8080 (Traefik dashboard) |

To add a new route, edit `lxc/traefik/dynamic/routers.yml` on CT 102 (Traefik watches for changes and auto-reloads).

---

## Shared Storage (NFS CSI)

```
    ┌──────────┐       NFSv3        ┌──────────────────┐
    │  UGreen  │ ◄─────────────────► │  CSI Node Plugin │  (system job on all 6 nodes)
    │   NAS    │   /volume1/UptonX   │                  │
    │  .11     │                     │  CSI Controller  │  (service job, count=1)
    └──────────┘                     └──────────────────┘
```

| | |
|---|---|
| **NAS** | 192.168.1.11 (UGreen), SSH: chris-admin@192.168.1.11 |
| **Export** | /volume1/UptonX |
| **Protocol** | NFSv3 (UGreen doesn't support NFSv4 properly) |
| **CSI Plugin** | `nfs` — registry.k8s.io/sig-storage/nfsplugin:v4.13.1 |

### How it works

1. The **CSI controller** (Nomad service job, 1 instance) handles volume provisioning and orchestration
2. The **CSI node plugin** (Nomad system job, all 6 nodes, privileged) handles mounting NFS shares into task containers
3. **Volumes** are registered with Nomad, each pointing to a directory on the NAS
4. Nomad jobs reference volumes by ID — the CSI plugin handles mounting/unmounting automatically

### Nomad Jobs

| Job | Type | File |
|-----|------|------|
| nfs-csi-controller | service (count=1) | `nomad/jobs/nfs-csi-controller.nomad.hcl` |
| nfs-csi-nodes | system (all nodes) | `nomad/jobs/nfs-csi-nodes.nomad.hcl` |

### Registered Volumes

| Volume ID | NAS Path | Access Mode |
|-----------|----------|-------------|
| test-data | /volume1/UptonX/test | multi-node-multi-writer |

Volume definitions are stored in `nomad/volumes/*.volume.hcl`.

### Adding a New Volume

```bash
# 1. Create the directory on the NAS
ssh chris-admin@192.168.1.11 "mkdir -p /volume1/UptonX/<name>"

# 2. Create volume definition (copy from test-data template)
cp nomad/volumes/test-data.volume.hcl nomad/volumes/<name>.volume.hcl
# Edit: change id, name, and share path

# 3. Register with Nomad
nomad volume register nomad/volumes/<name>.volume.hcl
```

---

## Services Summary

### Managed by Nomad

| Job | Type | Description |
|-----|------|-------------|
| nfs-csi-controller | service | NFS CSI controller plugin |
| nfs-csi-nodes | system | NFS CSI node plugin (runs on all nodes) |

### Standalone (Docker on LXCs)

| Service | Container | Host | Access |
|---------|-----------|------|--------|
| Technitium DNS | CT 101 | 192.168.1.51 | :53 (DNS), :5380 (web) |
| Traefik v3 | CT 102 | 192.168.1.15 | :80, :443, :8080 (dashboard) |

---

## Backups

**Proxmox Backup Server** runs on a dedicated machine at `192.168.1.19`. It is not part of the Nomad/Consul cluster. All Proxmox hypervisors can back up their LXCs and VMs to PBS.

---

## Repository Structure

```
uptonx-homelab/
├── CONTEXT.md                          # Quick reference (IPs, nodes, volumes)
├── docs/
│   └── INFRASTRUCTURE.md               # This document
├── nomad/
│   ├── configs/                         # Nomad node configurations
│   │   ├── lxc-server.hcl              #   CT 100 (nomad)
│   │   ├── aux2-server.hcl             #   CT 103 (nomad2)
│   │   ├── aux-server.hcl              #   CT 104 (nomad3)
│   │   ├── ai-nuc-client.hcl           #   CT 301 (nomad-ai)
│   │   ├── msi-client.hcl              #   CT 105 (nomad-msi)
│   │   └── workstation-client.hcl      #   workstation
│   ├── jobs/                            # Nomad job definitions
│   │   ├── nfs-csi-controller.nomad.hcl
│   │   └── nfs-csi-nodes.nomad.hcl
│   └── volumes/                         # CSI volume registrations
│       └── test-data.volume.hcl
└── lxc/
    ├── technitium/
    │   └── docker-compose.yml
    └── traefik/
        ├── docker-compose.yml
        ├── traefik.yml
        └── dynamic/
            └── routers.yml
```

---

## Quick Access

| What | URL / Command |
|------|---------------|
| Nomad UI | https://nomad.uptonx.com or http://192.168.1.101:4646 |
| Consul UI | http://192.168.1.101:8500 |
| Technitium DNS | https://dns.uptonx.com or http://192.168.1.51:5380 |
| Traefik Dashboard | https://traefik.uptonx.com or http://192.168.1.15:8080 |
| Nomad status | `nomad node status` |
| Consul members | `consul members` |
| CSI plugin health | `nomad plugin status nfs` |
| Volume list | `nomad volume status` |
