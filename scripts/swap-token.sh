#!/usr/bin/env bash
# Rota el WHATSAPP_ACCESS_TOKEN (token temporal de Meta) sin nano ni deploy.
#
# Uso EN EL VPS, desde el repo root:
#   bash scripts/swap-token.sh <NUEVO_TOKEN>
#
# Qué hace:
#   1. Reemplaza (o agrega) WHATSAPP_ACCESS_TOKEN en .env.prod.
#   2. Reinicia SOLO backend + worker (los que envían por Meta) para que tomen
#      la env nueva. Segundos, sin migraciones, sin rebuild.
#
# NO toca la DB ni el esquema. NO es un deploy. Seguro de correr las veces que
# haga falta mientras el token temporal de 24 h siga caducando.
set -euo pipefail

NEW="${1:?uso: bash scripts/swap-token.sh <nuevo_token>}"
VAR="${TOKEN_VAR:-WHATSAPP_ACCESS_TOKEN}"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

[ -f "$ENV_FILE" ] || { echo "no existe $ENV_FILE (¿estás en el repo root del VPS?)"; exit 1; }

# Reemplazo sin sed: el token trae / y = → filtrar la línea vieja y anexar la
# nueva evita cualquier problema de escape.
tmp="$(mktemp)"
grep -v "^${VAR}=" "$ENV_FILE" > "$tmp" || true
printf '%s=%s\n' "$VAR" "$NEW" >> "$tmp"
# Preservar permisos del original.
cat "$tmp" > "$ENV_FILE"
rm -f "$tmp"
echo "→ $VAR actualizado en $ENV_FILE"

echo "→ reiniciando backend + worker..."
docker compose -f "$COMPOSE_FILE" restart backend worker
echo "✓ token rotado y servicios reiniciados. El bot vuelve a enviar."
