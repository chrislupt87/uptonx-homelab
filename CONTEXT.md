# UptonX Homelab Context

## Active Services

### Email RAG Stack — 192.168.1.110
- **VM**: email-rag (VM 401) on AI box (192.168.1.69), Ubuntu 24.04, 56GB RAM, 12 cores, 1.2TB disk
- **Ollama**: native systemd, port 11434, models: snowflake-arctic-embed2, dolphin3:8b, qwen2.5:72b (CPU-only)
- **PostgreSQL 16**: native systemd, port 5432, pgvector enabled, tuned for 56GB RAM
- **FastAPI**: Docker, port 8000 (API), port 3000 (UI)
- **Traefik route**: email-rag.uptonx.com -> 192.168.1.110:3000
- **NFS**: helm:/mnt/nfs/volumes -> /mnt/nfs/volumes/email-rag/ (archive, config, backups)
- **Timers**: backup 01:00, ingest 02:00, analyze 03:00

### AI Box Dashboard — 192.168.1.69
- Chromium kiosk on tty1 -> email-rag UI
- Glances web: port 61208
- Fallback: /var/www/html/dashboard.html
