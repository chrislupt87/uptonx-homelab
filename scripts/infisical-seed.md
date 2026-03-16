# Infisical Project Structure

Project: **homelab** | Environment: **prod**

Organize secrets by folder (one per service). The `infisical-sync.sh` script
pulls from these paths and writes `.env` files to each host.

## Folder: /traefik
| Key | Description | Current source |
|-----|-------------|----------------|
| CF_API_EMAIL | Cloudflare account email | traefik docker-compose env |
| CF_DNS_API_TOKEN | Cloudflare API token (DNS edit) | traefik docker-compose env |

## Folder: /authentik
| Key | Description | Current source |
|-----|-------------|----------------|
| PG_PASS | PostgreSQL password | lxc/authentik/.env |
| AUTHENTIK_SECRET_KEY | Authentik secret key | lxc/authentik/.env |

## Folder: /frigate
| Key | Description | Current source |
|-----|-------------|----------------|
| NEST_CLIENT_ID | Google OAuth client ID | .env.example |
| NEST_CLIENT_SECRET | Google OAuth client secret | .env.example |
| NEST_REFRESH_TOKEN | Google OAuth refresh token | .env.example |
| NEST_PROJECT_ID | Google Device Access project ID | .env.example |
| NEST_CAM_NORTH_ID | Nest cam device ID (north) | .env.example |
| NEST_CAM_SOUTH_ID | Nest cam device ID (south) | .env.example |
| NEST_CAM_ENTRANCE_ID | Nest cam device ID (entrance) | .env.example |

## Folder: /video-ai
| Key | Description | Current source |
|-----|-------------|----------------|
| COMPREFACE_API_KEY | CompreFace recognition API key | generated in CompreFace UI |
| TELEGRAM_BOT_TOKEN | Telegram bot for face trainer | manual |
| TELEGRAM_CHAT_ID | Telegram chat ID | manual |

## Folder: /audio
| Key | Description | Current source |
|-----|-------------|----------------|
| HF_TOKEN | HuggingFace token (pyannote diarization) | manual |

## Folder: /email-rag
| Key | Description | Current source |
|-----|-------------|----------------|
| ANTHROPIC_API_KEY | Claude API key | vm/email-rag/secrets/email-rag.env |
| DB_PASSWORD | PostgreSQL password | vm/email-rag/secrets/email-rag.env |
| GMAIL_CREDENTIALS | Gmail API credentials JSON | vm/email-rag/secrets/ |

## Folder: /infisical
| Key | Description | Current source |
|-----|-------------|----------------|
| ENCRYPTION_KEY | Infisical encryption key | /opt/infisical/.env |
| AUTH_SECRET | Infisical auth secret | /opt/infisical/.env |
| POSTGRES_PASSWORD | Infisical DB password | /opt/infisical/.env |

## Setup Steps

1. Login to https://infisical.uptonx.com
2. Create project "homelab" if not exists
3. Create "prod" environment
4. Create folders listed above
5. Add secrets from current .env files
6. Install CLI on workstation: `sudo apt install infisical`
7. Run: `infisical login --domain https://infisical.uptonx.com`
8. Test: `./scripts/infisical-sync.sh traefik`
9. Deploy all: `./scripts/infisical-sync.sh --deploy`
