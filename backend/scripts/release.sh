#!/bin/sh
# Capa 0 (DEPLOY_VPS_PLAN.md): release step — one-shot per deploy.
#
# Runs:
#   1. migrate               → schema sync
#   2. collectstatic         → admin + DRF assets into staticfiles/ (Caddy)
#   3. seed_permissions      → idempotent RBAC permission/role seed
#   4. remediate_identity_f0 → degrada las verificaciones obtenidas por el
#                              bypass de identidad y cierra los retos de la FSM
#                              retirada (plan de continuidad, D16/D37)
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

# Va AQUÍ y no en una corrida manual posterior, por orden: este one-shot corre
# después de `migrate` y ANTES de levantar la versión nueva. El prompt v11 le
# dice al modelo que confíe en `verificado: true`; si la degradación esperara a
# que alguien la lanzara a mano, entre el deploy y ese momento el agente estaría
# confiando en un estado obtenido por el bypass que este trabajo cierra.
#
# Idempotente como el resto del script: solo toca lo que aún no está remediado.
echo "[release] remediate_identity_f0"
python manage.py remediate_identity_f0 --apply

echo "[release] done"
