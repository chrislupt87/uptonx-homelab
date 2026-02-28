# Homelab Swarm Deploy — Pre-Flight Checklist

Print this out. Check each box as you go.

---

## Before You Touch Anything

- [ ] Aux 2 (192.168.1.80) is powered on and reachable via SSH
- [ ] Docker is installed on Aux 2
- [ ] Docker is installed on all worker nodes
- [ ] NAS (192.168.1.11) is powered on and has an NFS share exported
- [ ] You know the NFS export path on the NAS (e.g. `/volume1/docker`)
- [ ] All stack files are copied to `/opt/stacks/` on Aux 2

---

## Secrets to Generate (write them down somewhere safe)

- [ ] **Traefik dashboard password** (htpasswd format)
      Generate: `htpasswd -nB admin`
      Result: `admin:$2y$05$...`
      Write it here: ________________________________________

- [ ] **Vaultwarden admin token**
      Generate: `openssl rand -base64 48`
      Write it here: ________________________________________

- [ ] **Generic DB password** (placeholder for future use)
      Generate: `openssl rand -base64 32`
      Write it here: ________________________________________

---

## Values to Fill In

| File | What to change | Change to |
|------|---------------|-----------|
| `init-storage.sh` | `NFS_EXPORT` path | Your NAS export path (line 9) |
| `init-secrets.sh` | `TRAEFIK_DASHBOARD_AUTH` | htpasswd string from above |
| `init-secrets.sh` | `VAULTWARDEN_ADMIN_TOKEN` | Token from above |
| `init-secrets.sh` | `DB_PASSWORD` | Password from above |
| `join-workers.sh` | `JOIN_TOKEN` | Output of `docker swarm join-token worker` |

---

## Self-Signed TLS Cert

- [ ] Generate cert (run on Aux 2 after storage is mounted):
```
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /mnt/nas/stacks/traefik/certs/key.pem \
  -out /mnt/nas/stacks/traefik/certs/cert.pem \
  -subj "/CN=homelab.local"
```

---

## Execution Order

Run from your workstation unless noted otherwise.

- [ ] **Step 1** — `./init-context.sh` (workstation only)
      Verify: `docker info` shows Aux 2

- [ ] **Step 2** — `./init-swarm.sh`
      Verify: `docker node ls` shows one manager

- [ ] **Step 3** — `./init-storage.sh`
      Verify: `df -h /mnt/nas` shows NAS mount

- [ ] **Step 4** — Edit `init-secrets.sh` with real values, then run it
      Verify: `docker secret ls` shows 3 secrets

- [ ] **Step 5** — Generate TLS cert (see above)
      Verify: `ls /mnt/nas/stacks/traefik/certs/` shows cert.pem + key.pem

- [ ] **Step 6** — Get join token: `docker swarm join-token worker`
      Paste into `join-workers.sh`, then run it
      Verify: `docker node ls` shows 5 nodes

- [ ] **Step 7** — `./deploy-all.sh`
      Verify: `docker stack ls` shows 6 stacks

---

## Post-Deploy Smoke Test

- [ ] Traefik dashboard: `http://192.168.1.80:8080/dashboard/`
- [ ] Portainer: `http://192.168.1.80:9000`
- [ ] Technitium DNS UI: `http://192.168.1.80:5380`
- [ ] Vaultwarden: `http://192.168.1.80:8880`
- [ ] Uptime Kuma: `http://192.168.1.80:3001`
- [ ] DNS resolution: `dig @192.168.1.80 google.com`
- [ ] HTTPS redirect: `curl -I http://192.168.1.80` → 301 to https

---

## First-Login Tasks

- [ ] Portainer: Create admin account on first visit
- [ ] Technitium: Change default admin password
- [ ] Vaultwarden: Create your account, then set `SIGNUPS_ALLOWED=false`
- [ ] Uptime Kuma: Create admin account, add monitors for each service

---

## Node Quick Reference

| Name | IP | Role |
|------|----|------|
| Aux 2 | 192.168.1.80 | Manager |
| Aux | 192.168.1.18 | Worker |
| MSI | 192.168.1.74 | Worker |
| Control | 192.168.1.77 | Worker |
| AI Node | 192.168.1.69 | Worker |
| NAS | 192.168.1.11 | Storage (NFS) |
