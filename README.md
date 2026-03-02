# UptonX Homelab Infrastructure

Hypervisor: Proxmox VE | DNS: Technitium | Reverse Proxy: Traefik v3

## Proxmox Hosts

| Host | IP | Role |
|------|----|------|
| helm | 192.168.1.77 | Primary PVE host |
| aux | 192.168.1.18 | PVE host |
| aux2 | 192.168.1.80 | PVE host |
| ai | 192.168.1.69 | AI NUC |
| msi | 192.168.1.74 | PVE host |
| pbs | 192.168.1.19 | Proxmox Backup Server |
| nas | 192.168.1.11 | UGreen NAS |

## Active Services

| Service | Container | IP | Status |
|---------|-----------|-----|--------|
| Technitium DNS | CT 101 | 192.168.1.51 | Running |
| Traefik v3 | CT 102 | 192.168.1.15 | Running |

## Repo Structure

```
lxc/
  technitium/   # DNS server config
  traefik/      # Reverse proxy config + dynamic routes
```
