# Homelab Docker Swarm Stack

## Run Order

Execute these scripts in sequence. Nothing is deployed until `deploy-all.sh`.

| Step | Script | Where it runs | What it does |
|------|--------|---------------|--------------|
| 1 | `init-context.sh` | **Workstation** | Creates Docker context `aux2` targeting the Swarm manager |
| 2 | `init-swarm.sh` | Aux 2 (via context) | Initializes Swarm, creates overlay networks, labels manager |
| 3 | `init-storage.sh` | Aux 2 (via context) | Mounts NAS via NFS, creates persistent volume directories |
| 4 | `init-secrets.sh` | Aux 2 (via context) | Creates Docker secrets (edit placeholders first!) |
| 5 | `join-workers.sh` | Workstation → SSH | Joins all worker nodes to the swarm (edit token first!) |
| 6 | `deploy-all.sh` | Aux 2 (via context) | Deploys all stacks in dependency order |

## Services

| Service | URL | Port | Network | Description |
|---------|-----|------|---------|-------------|
| Traefik | `http://192.168.1.80:8080/dashboard/` | 80, 443, 8080 | proxy | Reverse proxy with self-signed TLS, HTTP→HTTPS redirect |
| Portainer | `http://192.168.1.80:9000` | 9000 | proxy | Docker Swarm management UI |
| Technitium | `http://192.168.1.80:5380` | 53 (TCP/UDP), 5380 | internal | DNS server with web admin panel |
| Vaultwarden | `http://192.168.1.80:8880` | 8880 | proxy | Bitwarden-compatible password manager |
| Uptime Kuma | `http://192.168.1.80:3001` | 3001 | proxy | Service uptime monitoring dashboard |
| Watchtower | — (no UI) | — | internal | Monitor-only container update checker (nightly at 3 AM) |

## Networks

| Network | Type | Subnet | Purpose |
|---------|------|--------|---------|
| `proxy` | overlay | 10.10.0.0/24 | Services exposed via Traefik |
| `internal` | overlay (--internal) | auto | Backend-only services, no external access |

## Container IP Pool

`192.168.1.100–125` — reserved for container use on the host network.

## Swarm Nodes

| Node | Role | IP |
|------|------|----|
| Aux 2 | **Manager** | 192.168.1.80 |
| Aux | Worker | 192.168.1.18 |
| MSI | Worker | 192.168.1.74 |
| Control | Worker | 192.168.1.77 |
| AI Node | Worker | 192.168.1.69 |

## Persistent Storage (NAS)

All service data is stored on the UGreen NAS at `192.168.1.11`, mounted via NFS to `/mnt/nas` on Aux 2.

| Service | NAS Path |
|---------|----------|
| Traefik | `/mnt/nas/stacks/traefik` |
| Portainer | `/mnt/nas/stacks/portainer` |
| Technitium | `/mnt/nas/stacks/technitium` |
| Vaultwarden | `/mnt/nas/stacks/vaultwarden` |
| Uptime Kuma | `/mnt/nas/stacks/uptime-kuma` |
| Watchtower | `/mnt/nas/stacks/watchtower` |

## Self-Signed TLS

Traefik uses a self-signed certificate. Generate it before first deploy:

```bash
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /mnt/nas/stacks/traefik/certs/key.pem \
  -out /mnt/nas/stacks/traefik/certs/cert.pem \
  -subj "/CN=homelab.local"
```

## Secrets

| Secret Name | Used By | How to Generate |
|-------------|---------|-----------------|
| `traefik_dashboard_auth` | Traefik | `htpasswd -nB admin` |
| `vaultwarden_admin_token` | Vaultwarden | `openssl rand -base64 48` |
| `db_password` | (placeholder) | `openssl rand -base64 32` |

Edit values in `init-secrets.sh` before running.

## Directory Structure

```
/opt/stacks/
├── init-context.sh      # Step 1 — workstation only
├── init-swarm.sh        # Step 2
├── init-storage.sh      # Step 3
├── init-secrets.sh      # Step 4
├── join-workers.sh      # Step 5
├── deploy-all.sh        # Step 6
├── README.md
├── traefik/
│   ├── stack.yml
│   └── dynamic/
│       └── tls.yml
├── portainer/
│   └── stack.yml
├── technitium/
│   └── stack.yml
├── vaultwarden/
│   └── stack.yml
├── uptime-kuma/
│   └── stack.yml
├── watchtower/
│   └── stack.yml
├── shared/
└── secrets/
```
