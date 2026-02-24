# UptonX Homelab Infrastructure

Orchestration: Docker Swarm | Hypervisor: Proxmox | Shell: zsh

## Network

| Device | IP | Role |
|--------|----|------|
| UniFi Gateway | 192.168.1.1 | Router |
| UGreen NAS | 192.168.1.11 | Storage |
| Traefik | 192.168.1.12 | Reverse proxy |
| Technitium DNS (LXC) | 192.168.1.15 | Primary DNS |
| Aux | 192.168.1.18 | Proxmox node |
| PBS | 192.168.1.19 | Proxmox Backup Server |
| AI NUC | 192.168.1.69 | Always-on AI inference |
| MSI Workstation | 192.168.1.74 | GPU node (AMD RX 7600) |
| Control | 192.168.1.77 | Swarm manager |
| Frigate | 192.168.1.80 | NVR / cameras |
| Display Pi | 192.168.1.91 | Touchscreen dashboard |
| Technitium DNS (Pi) | 192.168.1.92 | Secondary DNS |

## Swarm Layout
```
Control (1.77)     ← Swarm Manager
├── AI NUC (1.69)  ← Worker [role=ai]
├── MSI (1.74)     ← Worker [role=gpu]
├── Frigate (1.80) ← Worker [role=camera]
└── Aux (1.18)     ← Worker [role=general]
```

## Service Map

| Service | Node | Port |
|---------|------|------|
| Traefik | Control | 80/443 |
| Authentik | Control | 9000 |
| Portainer | Control | 9443 |
| Cloudflare Tunnel | Control | - |
| Ollama | AI NUC | 11434 |
| Qdrant | AI NUC | 6333 |
| PostgreSQL | AI NUC | 5432 |
| LiteLLM | AI NUC | 4000 |
| RAG API | AI NUC | 8000 |
| RAG UI | AI NUC | 3001 |
| LibreChat | AI NUC | 3080 |
| n8n | AI NUC | 5678 |
| Frigate NVR | Frigate | 5000 |

## Common Commands
```zsh
# Deploy a stack
docker stack deploy -c services/ai/ollama/stack.yml ollama

# Deploy everything
./scripts/deploy.zsh

# Check health
./scripts/health-check.zsh

# View logs
docker service logs <service_name> -f

# Check nodes
docker node ls
```
