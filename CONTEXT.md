# UptonX Homelab — Infrastructure Context

## Orchestration
- **Scheduler**: HashiCorp Nomad 1.11.2
- **Datacenter**: uptonx
- **Region**: global

## Nodes

| Host | IP | Role | Notes |
|------|----|------|-------|
| helm | 192.168.1.77 | Proxmox host | Hypervisor, manages LXCs/VMs |
| nomad (CT 100) | 192.168.1.101 | Nomad server + client | Ubuntu 24.04 LXC on helm |
| technitium (CT 101) | 192.168.1.51 | DNS server | Ubuntu 24.04 LXC on helm, Technitium DNS |
| traefik (CT 102) | 192.168.1.15 | Reverse proxy | Ubuntu 24.04 LXC on helm, Traefik v3 |
| uptonx-workstation | 192.168.1.95 | Nomad client | Kubuntu, AMD RX 7600 GPU |

## Nomad Cluster

- **Server**: 192.168.1.101 (single server, bootstrap_expect=1)
- **Clients**: 192.168.1.101, 192.168.1.95
- **UI**: http://192.168.1.101:4646
- **Configs**: `nomad/configs/`

## Running Services

| Service | Type | Status |
|---------|------|--------|
| Nomad cluster | Infrastructure | 2 nodes, operational |
| Technitium DNS | DNS | http://192.168.1.51:5380, port 53 |
| Traefik | Reverse proxy | http://192.168.1.15:8080, ports 80/443 |

## DNS (Technitium)

- **Server**: 192.168.1.51 (CT 101)
- **Web UI**: http://192.168.1.51:5380 (admin/admin)
- **Zones**: `uptonx.local` (internal hosts), `uptonx.com` (split-horizon wildcard → Traefik)
- **Forwarders**: 1.1.1.1, 1.0.0.1

## Reverse Proxy (Traefik v3)

- **Server**: 192.168.1.15 (CT 102)
- **Dashboard**: http://192.168.1.15:8080
- **HTTPS**: Cloudflare DNS challenge, wildcard `*.uptonx.com`
- **Routes**: `nomad.uptonx.com`, `dns.uptonx.com`, `traefik.uptonx.com`
- **Config**: File provider (`dynamic/routers.yml`)

## Network

- Subnet: 192.168.1.0/24
- Gateway: 192.168.1.1
- Internal domain: uptonx.local
- External domain: uptonx.com (Cloudflare)

## Other Infrastructure

| Host | IP | Role |
|------|----|------|
| pbs | 192.168.1.19 | Proxmox Backup Server |
| nas | 192.168.1.11 | UGreen NAS (user: chris-admin) |
| aux | 192.168.1.18 | Available |
| aux2 | 192.168.1.80 | Available |
| ai | 192.168.1.69 | AI NUC (available) |
| msi | 192.168.1.74 | MSI workstation (available) |
