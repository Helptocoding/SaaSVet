#!/bin/sh
# Capa 0 (DEPLOY_VPS_PLAN.md): release step — one-shot per deploy.
#
# Runs:
#   1. migrate          → schema sync
#   2. collectstatic    → admin + DRF assets into staticfiles/ (served by Caddy)
#   3. seed_permissions → idempotent RBAC permission/role seed
#
# Invoked by:
#   - docker-compose.prod.yml service `release` (condition: service_completed_successfully)
#   - Railway/Heroku `release:` Procfile entry
#
# IMPORTANT: must be idempotent. Re-running on the same DB must be a no-op.
# All three commands above are safe to run multiple times.

set -eu

cd /app

echo "[release] migrate --no-input"
python manage.py migrate --no-input

echo "[release] collectstatic --no-input"
python manage.py collectstatic --no-input

echo "[release] seed_permissions"
python manage.py seed_permissions

echo "[release] done"
