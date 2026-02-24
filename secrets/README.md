# Secrets Management

Secrets are NEVER committed to this repository.

## File Locations on Nodes
```
/opt/uptonx/
├── secrets/          ← Docker secrets
├── env/              ← .env files per service
└── data/             ← Persistent volumes
```

## Required Secrets

| Secret | Used By |
|--------|---------|
| postgres_password | PostgreSQL |
| authentik_secret_key | Authentik |
| litellm_master_key | LiteLLM |
| cloudflare_tunnel_token | Cloudflare |
| n8n_encryption_key | n8n |
