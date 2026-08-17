#!/bin/sh
# Capa 0 (DEPLOY_VPS_PLAN.md): release step — one-shot per deploy.
#
# Runs:
#   1. migrate               → schema sync
#   2. collectstatic         → admin + DRF assets into staticfiles/ (Caddy)
#   3. seed_permissions      → idempotent RBAC permission/role seed
#
# Invoked by:
#   - docker-compose.prod.yml service `release` (condition: service_completed_successfully)
#   - Railway/Heroku `release:` Procfile entry
#
# IMPORTANT: must be idempotent. Re-running on the same DB must be a no-op.
# All three commands above are safe to run multiple times.
#
# ── Este script NO corre remediaciones de datos ─────────────────────────────
#
# `remediate_identity_f0` estuvo aquí un día y causó el peor incidente del
# piloto. Dos motivos, y el segundo es el que importa para cualquier comando
# futuro:
#
# 1. **Esto no corre «una vez por deploy».** El cron de la demo
#    (`10,40 * * * *`) invoca `docker compose run --rm backend …`, y `run`
#    arranca las dependencias del servicio — entre ellas `release`. Así que este
#    script corre **cada 30 minutos** en producción. Cualquier cosa que se ponga
#    aquí hay que diseñarla para eso, no para un deploy.
#
# 2. **Una remediación es de un solo uso; este script no lo es.** Su predicado
#    describe un estado histórico que se quiere corregir. En cuanto el código
#    nuevo empieza a producir estados legítimos parecidos, el predicado los
#    alcanza — que es exactamente lo que pasó: degradaba toda verificación
#    conversacional, incluidas las correctas, cada media hora.
#
# Una remediación va a mano, con su ventana temporal explícita y con dry-run
# antes. `migrate`/`collectstatic`/`seed_permissions` se quedan porque son
# convergentes: su resultado no depende de cuándo corrieron.

set -eu

cd /app

echo "[release] migrate --no-input"
python manage.py migrate --no-input

echo "[release] collectstatic --no-input"
python manage.py collectstatic --no-input

echo "[release] seed_permissions"
python manage.py seed_permissions

echo "[release] done"
