# UptonX Homelab Infrastructure

Hypervisor: Proxmox VE | DNS: Technitium | Reverse Proxy: Traefik v3

## Proxmox Hosts

| Host | IP | Role |
|------|----|------|
| helm | 192.168.1.77 | PVE host |
| aux | 192.168.1.18 | PVE host |
| aux2 | 192.168.1.80 | PVE host (core services) |
| ai | 192.168.1.69 | AI NUC |
| msi | 192.168.1.74 | PVE host |
| pbs | 192.168.1.19 | Proxmox Backup Server |
| nas | 192.168.1.11 | UGreen NAS |

## Active Services

| Service | CT ID | PVE Host | IP | URL |
|---------|-------|----------|----|-----|
| Technitium DNS | 101 | aux2 | 192.168.1.51 | dns.uptonx.com |
| Traefik v3 | 102 | aux2 | 192.168.1.15 | traefik.uptonx.com |
| Gitea | 103 | helm | 192.168.1.20 | gitea.uptonx.com |
| Portainer | 104 | helm | 192.168.1.21 | portainer.uptonx.com |
| Infisical | 105 | helm | 192.168.1.22 | infisical.uptonx.com |

## Repo Structure

```
lxc/
  technitium/   # DNS server config
  traefik/      # Reverse proxy config + dynamic routes
  gitea/        # Git hosting
  portainer/    # Container management
  infisical/    # Secrets management
```
