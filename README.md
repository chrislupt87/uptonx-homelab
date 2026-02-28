# UptonX Homelab Infrastructure

Orchestration: Docker Swarm | Hypervisor: Proxmox | Shell: zsh
Status: Building out from Aux2 (192.168.1.80) — rolling deployment

## Nodes

| Host | IP | User | Role |
|------|----|------|------|
| control | 192.168.1.77 | root | Swarm manager (pending) |
| aux | 192.168.1.18 | root | Worker (pending) |
| aux2 | 192.168.1.80 | root | Active — build node |
| ai | 192.168.1.69 | root | AI inference (pending) |
| msi | 192.168.1.74 | root | GPU node (pending) |
| pbs | 192.168.1.19 | root | Proxmox Backup Server |
| nas | 192.168.1.11 | chris-admin | UGreen NAS storage |

## Swarm Status

Single node for now — Aux2 only. Other nodes join as services are verified.

## Active Services

| Service | Node | Port | Status |
|---------|------|------|--------|
| Traefik | Aux2 | 80/443 | 🔲 pending |

## Deployment Order

1. Docker on Aux2
2. Swarm init on Aux2
3. Traefik (reverse proxy + SSL)
4. Core services one at a time
5. Join next node, repeat

## Common Commands
```zsh
# Deploy a stack
docker stack deploy -c services/networking/traefik/stack.yml traefik

# Check cluster
docker node ls

# Check services
docker service ls

# Logs
docker service logs <service> -f

# Health check
./scripts/health-check.zsh
```

## SSH Shortcuts
```zsh
ssh control   # 192.168.1.77
ssh aux       # 192.168.1.18
ssh aux2      # 192.168.1.80
ssh ai        # 192.168.1.69
ssh msi       # 192.168.1.74
ssh pbs       # 192.168.1.19
ssh nas       # 192.168.1.11
```
