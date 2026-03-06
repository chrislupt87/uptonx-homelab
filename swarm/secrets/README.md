# Swarm Secrets Management

## Setup

1. Copy `swarm.env.example` to the swarm manager:
   ```bash
   scp swarm.env.example root@192.168.1.23:/opt/secrets/swarm.env
   ```

2. SSH in and fill in the values:
   ```bash
   ssh root@192.168.1.23
   nano /opt/secrets/swarm.env
   chmod 600 /opt/secrets/swarm.env
   ```

3. Load secrets into Docker Swarm:
   ```bash
   ./load-secrets.sh
   ```

## Files

- `swarm.env.example` — template with all required keys (no values)
- `load-secrets.sh` — reads swarm.env and creates Docker secrets
- Actual `swarm.env` is NEVER committed to git
