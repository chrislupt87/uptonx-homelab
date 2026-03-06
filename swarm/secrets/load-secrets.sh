#!/usr/bin/env bash
set -euo pipefail

# Load secrets from swarm.env into Docker Swarm secrets
# Run this on the swarm manager or via SSH

MANAGER="root@192.168.1.23"
ENV_FILE="/opt/secrets/swarm.env"

echo "Loading secrets from $ENV_FILE on manager..."

ssh "$MANAGER" bash -s << 'REMOTE'
set -euo pipefail
ENV_FILE="/opt/secrets/swarm.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy swarm.env.example and fill in values."
    exit 1
fi

while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    # Strip whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

    if [ -z "$value" ]; then
        echo "SKIP: $key (empty value)"
        continue
    fi

    # Convert to lowercase for docker secret name
    secret_name=$(echo "$key" | tr '[:upper:]' '[:lower:]')

    # Remove existing secret if it exists
    docker secret rm "$secret_name" 2>/dev/null && echo "  removed old: $secret_name"

    # Create new secret
    echo -n "$value" | docker secret create "$secret_name" -
    echo "  created: $secret_name"
done < "$ENV_FILE"

echo ""
echo "Current secrets:"
docker secret ls
REMOTE
