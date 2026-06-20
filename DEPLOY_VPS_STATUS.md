# Deploy VPS — Estado actual

Snapshot al **2026-05-26**. Plan completo en [DEPLOY_VPS_PLAN.md](./DEPLOY_VPS_PLAN.md). Runbooks en [docs/runbooks/](./docs/runbooks/).

**Resumen ejecutivo**: 8 de 9 capas completadas + commiteadas. Capa 9 (deploy real) pendiente — bloqueada por contratación VPS. Repo está LISTO para deploy: cero código pendiente, solo ejecución.

---

## Estado por capa

| Capa | Estado | Commits | Smoke local |
|------|--------|---------|-------------|
| **0** Código backend prep | ✅ DONE | `e4d49a2` | 394 tests OK |
| **1** Containerización | ✅ DONE | `f6ee0a3` + `60e9d5d` | backend 105MB, frontend 21.4MB content, non-root, healthcheck OK |
| **2** Compose orquestación | ✅ DONE | `9debb21` | postgres→release→backend→frontend healthy en orden |
| **3** Caddy + TLS + headers + CSP | ✅ DONE | `37a3dd8` + `a143aab` | HTTPS local con internal CA, HSTS/CSP/X-Frame todos presentes |
| **4** Postgres backup/restore | ✅ DONE | `e72c01a` | dump 225KB + restore a DB nueva con 12 tablas |
| **5** VPS hardening (runbook) | ✅ DONE | `f7e8a73` | n/a — runbook puro |
| **6** Cron jobs | ✅ DONE | `8a4e1e4` | 4/4 commands exit 0 |
| **7** Observability | ✅ DONE | `4b638f3` | settings load + disk-alert ambos paths verde |
| **8** Pre-launch security review | ✅ DONE | `2462c77` | pip-audit + pnpm audit 0 CVEs, script detecta 5 BLOCKERs en smoke |
| **9** Deploy real al VPS | ⛔ PENDIENTE | — | requiere VPS + dominio |

---

## Archivos creados/modificados (todos commiteados)

### Código backend
- `backend/apps/core/views.py` — `healthz` + `readyz` plain Django views, `@require_safe`
- `backend/config/urls.py` — paths `/api/healthz/` + `/api/readyz/`
- `backend/config/settings.py` — múltiples cambios:
  - LOGGING file handler condicional (solo dev/staging)
  - `SECURE_PROXY_SSL_HEADER` + `USE_X_FORWARDED_HOST` + `SECURE_REDIRECT_EXEMPT`
  - `conn_max_age` env-driven default 60s
  - Sentry `traces_sample_rate` env-driven + `environment` + `release` tags
- `backend/Procfile` — split `release:` one-shot vs `web:` solo gunicorn + `nightly_flush_jwt:`
- `backend/requirements.txt` — `psycopg2-binary` → `psycopg[binary]>=3.1`
- `backend/requirements.lock` — pip-compile snapshot
- `backend/scripts/release.sh` — migrate + collectstatic + seed_permissions

### Imágenes Docker
- `backend/Dockerfile` — multi-stage python:3.13-slim, non-root `app`, wheels pre-built
- `backend/.dockerignore`
- `frontend/Dockerfile` — node:20-alpine build → nginx:1.27-alpine static
- `frontend/.dockerignore`
- `frontend/nginx-spa.conf` — SPA try_files fallback + asset cache 1y + index.html no-cache

### Orquestación
- `docker-compose.prod.yml` — postgres + release + backend + frontend + caddy con healthchecks + depends_on + resource limits
- `.env.prod.example` — plantilla 105+ líneas, TODOS los vars documentados
- `.gitignore` — `.env.prod*` excluido, `.env.prod.example` whitelist
- `.gitattributes` — LF enforce para `*.sh`, Dockerfile, Caddyfile, `*.yml`

### Reverse proxy
- `infra/Caddyfile` — TLS auto, HSTS, X-Frame, Referrer-Policy, Permissions-Policy, CSP estricta, encode gzip+zstd, `/admin/` IP-allowlist block (comentado), JSON logs stdout

### Scripts host
- `scripts/pg-backup.sh` (+x) — `pg_dump -Fc` via docker exec, retention 14d configurable, rclone offsite + healthchecks.io ping opcionales
- `scripts/pg-restore.sh` (+x) — restore SIEMPRE a DB nueva, refuse target=live DB, smoke row counts en 12 tablas
- `scripts/disk-alert.sh` (+x) — hourly cron, webhook Slack/Discord/HC.io si >80% en `/`, `/var/lib/docker`, `/var/backups/vet`
- `scripts/crontab.example` — 5 entries (pg-backup, flushexpiredtokens, build_daily_metrics, audit_anchor_integrity, disk-alert, journalctl vacuum semanal)
- `scripts/pre-launch-security-check.sh` (+x) — 12 categorías de auditoría, exit 0/1/2

### Runbooks
- `docs/runbooks/vps-hardening.md` — 13 secciones (Ubuntu setup: user deploy, SSH lockdown, UFW, fail2ban, Docker, log rotation, swap, timezone, dirs, verificación, gotchas, ops recurrentes)
- `docs/runbooks/cron-jobs.md` — install crontab, perms logs, logrotate, healthchecks.io deadman, troubleshooting
- `docs/runbooks/observability.md` — Sentry backend/frontend, UptimeRobot HTTP probe, disk-alert webhook formats, log grep patterns, cuándo upgradear a Loki
- `docs/runbooks/pre-launch-security.md` — script + manual checks + CVE policy + decisiones diferidas

### Plan + documentación
- `DEPLOY_VPS_PLAN.md` — plan original por capas
- `DEPLOY_VPS_STATUS.md` — este archivo

---

## Capa 9 — PENDIENTE (lo que falta hacer)

Bloqueada por:
- **VPS contratado** (Vultr HF MX, Hetzner CX22, o equivalente)
- **Dominio** con DNS A-record apuntando al IPv4 del VPS

### Secuencia Capa 9 cuando esté el VPS

```bash
# 1. SSH inicial al VPS (con la IP que te dé el provider)
ssh root@<VPS_IP>

# 2. Correr Capa 5 — vps-hardening.md §1-§11 (1-2h)
#    Resultado: user `deploy` + SSH keys-only + UFW + Docker + log rotation + swap + UTC

# 3. Clone del repo
ssh deploy@<VPS_IP>
cd /opt/vet
git clone <tu-repo-url> app
cd app

# 4. Crear .env.prod desde plantilla
cp .env.prod.example .env.prod
nano .env.prod   # rellenar TODO (SECRET_KEY, dominio, DB password, Sentry DSNs)
chmod 600 .env.prod

# 5. Build imágenes
docker compose -f docker-compose.prod.yml --env-file .env.prod build

# 6. Up postgres + wait healthy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod ps    # esperar (healthy)

# 7. Release one-shot
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release

# 8. Bootstrap superuser MANUAL (única vez, NO en env)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py createsuperuser

# 9. Up stack completo
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# 10. Smoke
curl -fsS https://app.tu-dominio.com/api/healthz/    # 200 ok
curl -fsS https://app.tu-dominio.com/api/readyz/     # 200 ready
curl -I  https://app.tu-dominio.com/                 # 200 + headers seguros

# 11. Pre-launch security check
./scripts/pre-launch-security-check.sh               # debe exit 0

# 12. Setup crons
sudo touch /var/log/vet-{backup,cron,anchor}.log
sudo chown deploy:deploy /var/log/vet-*.log
crontab scripts/crontab.example
crontab -l   # verificar

# 13. Smoke E2E manual (navegador):
#     - login admin SaaS
#     - provision org via /api/platform/organizations/
#     - login admin org → crear Owner+Pet+Appointment+MedicalRecord+Invoice
#     - change-password

# 14. UptimeRobot monitor + Sentry alert rules + (opcional) Healthchecks.io deadman

# 15. Restart VPS — verificar auto-recovery
sudo reboot
# tras reboot: docker compose ps debe mostrar todos healthy sin intervención
```

---

## Backlog acción tuya (U1-U37 agregados)

### Ya completados (gracias)
- ✅ U1 generar requirements.lock
- ✅ U2 smoke psycopg v3 local
- ✅ U4 commits Capa 0
- ✅ U6 commit Capa 1 (con bug — frontend faltó, fix en U8)
- ✅ U8 follow-up Capa 1 frontend files
- ✅ U9 commit Capa 2
- ✅ U10 verify `.env.prod` no tracked

### Pre-VPS (puedes hacer cuando quieras)
- U20 Contratar VPS (Vultr HF MX recomendado para latencia / Hetzner CX22 para precio)
- U21 Generar SSH key `ssh-keygen -t ed25519 -f ~/.ssh/vet_vps`
- U22 Comprar dominio + crear A record → IP VPS (Cloudflare DNS / Namecheap / GoDaddy)
- U23 Lectura completa `docs/runbooks/vps-hardening.md` ANTES de tocar VPS

### Pre-launch (1-2h trabajo + cuentas externas)
- U29 Cuenta Sentry + 2 projects (vet-backend + vet-frontend) + DSNs en `.env.prod`
- U30 Cuenta UptimeRobot + monitor HTTPS `/api/healthz/` cada 5min
- U31 (opcional) Slack workspace + incoming webhook URL → `ALERT_WEBHOOK` en cron
- U28 (opcional) Healthchecks.io free + 4 checks deadman para crons

### Día de deploy (Capa 9 — sigue secuencia arriba)
- U24 Ejecutar runbook hardening §1-§11
- U25-U27 Setup crons + logs + logrotate
- U33 Pre-launch check exit 0
- U34 SSL Labs grade A+
- U35 E2E manual navegador
- U36 Rate limit smoke (6 logins fallidos → último 429)

### Ops recurrentes post-launch
- U32 Cada deploy: `SENTRY_RELEASE=$(git rev-parse --short HEAD)` en `.env.prod` antes de build
- U37 Cada release: re-correr `pre-launch-security-check.sh` + `pip-audit` + `pnpm audit`

### Pre-launch decisión pendiente (HIGH H4)
- U13 Decidir admin `/admin/` hardening:
  - **Opción A**: dejar tal cual (Django auth + throttle, aceptable beta)
  - **Opción B**: IP allow-list en Caddyfile (solo si IP residencial estable)
  - **Opción C**: path obfuscation + Caddy basic-auth (recomendado si IP dinámica)
  - **Opción D**: Cloudflare Access (medio esfuerzo, escala con equipo)
  - Decisión pendiente — la doy contigo cuando tengas VPS

---

## Decisiones arquitectónicas tomadas (referencia rápida)

| Decisión | Razón |
|----------|-------|
| **Caddy** (no nginx + certbot) | TLS automático, config 5x más corta, HTTP/3 nativo |
| **Sin Redis/Celery** | No tasks async fuera del cron nightly — overengineering para beta |
| **Sin PgBouncer** | <50 RPS — Postgres direct aguanta, `conn_max_age=60` controla pool |
| **Named volume pgdata (no bind-mount)** | Backup via `docker exec` no necesita acceso directo al host filesystem — evita perms 999:999 headaches |
| **Plain Django views para healthz/readyz** | Bypasa DRF + DEFAULT_PERMISSION_CLASSES sin boilerplate AllowAny |
| **`require_safe` en healthz/readyz** | Acepta GET + HEAD — UptimeRobot prefiere HEAD a veces |
| **`SECURE_REDIRECT_EXEMPT` healthz** | Container healthcheck es loopback http — sin exempt Django redirige 301 → "unhealthy" |
| **Caddy healthcheck → listener interno `http://localhost:8081`** | El bloque público `{$DOMAIN}` fuerza HTTP→HTTPS y su cert es del dominio, no `localhost` → probe loopback sobre `:80`/`:443` falla (busybox wget sin TLS confiable). Listener `http://` dedicado: sin redirect, sin TLS, sin ACME; responde 200 puro (liveness, desacoplado del backend). Puerto 8081 NO publicado → invisible desde internet |
| **`run --rm backend` en crons** | Container fresh aísla de issues runtime — 5-10s overhead aceptable para crons diarios |
| **Crons como `deploy`, NO root** | Mismo principio que SSH hardening — único cron que usa sudo es journalctl vacuum |
| **Horarios cron en UTC** | Host UTC + Django UTC + Postgres UTC = cero ambigüedad correlación |
| **Sentry `traces_sample_rate=0.05`** | Free tier ~10K trans/mes — 5% bajo carga típica beta queda holgado |
| **psycopg v3 [binary]** | Wheel autocontenido (no necesita libpq en runtime) + activo upstream vs psycopg2 legacy |
| **Frontend HTTP/health no público** | Caddy es único entrypoint — backend/frontend/postgres invisibles desde internet |
| **Sin Kubernetes / Swarm / Nomad** | 1 VPS, beta cerrada — orquestadores son overengineering 10x vs compose |

---

## Decisiones diferidas a post-beta (documentado, NO bloqueante)

| Item | Cuándo |
|------|--------|
| 2FA / MFA admin (django-otp TOTP) | Phase 3 |
| WAF Cloudflare proxy | Cuando aparezca tráfico bot |
| fail2ban jail para Django LOGIN_FAILED | Phase 2 — throttle DRF ya cubre baseline |
| CSP `report-uri` | Cuando integres dashboard de violaciones |
| Sentry source maps upload via sentry-cli | Cuando pyo necesites stacktraces frontend legibles |
| `pip-compile --generate-hashes` para supply chain | Phase 2 |
| Penetration test profesional | Post-launch cuando haya datos reales |
| Bug bounty público | Phase 3 escala |
| Loki + Promtail (log shipping) | Cuando tengas >3 servicios o queries históricas |
| Pgbouncer + read replicas | Cuando Postgres >70% CPU sostenido |
| Blue-green deploy | Cuando downtime ~30s del rebuild moleste |
| CI/CD GitHub Actions | Cuando manual `git pull && build` moleste |

---

## Sizing + costos VPS recomendados

Beta cerrada (<100 usuarios concurrentes):

| Provider | Tier | Specs | Precio | Latencia desde MX |
|----------|------|-------|--------|-------------------|
| **Vultr HF MX** ⭐ | High Frequency 2C/4GB | 2vCPU AMD / 4GB / 128GB NVMe / 3TB BW | $24/mes | ~20ms (DC MX City) |
| **Hetzner CX22** | shared vCPU | 2vCPU / 4GB / 40GB SSD / 20TB BW | €4.51/mes | ~150ms (EU) |
| **DigitalOcean Premium AMD** | shared | 2vCPU / 4GB / 80GB SSD | $24/mes | ~80ms (NYC/SFO) |

Bottleneck primero: Postgres I/O + RAM. Escala vertical primero (4GB→8GB) antes de descomponer.

---

## Resumen 1-pantalla

- Repo READY. Cero código pendiente.
- 8/9 capas completas. 9 commits Capa 0-8.
- Smoke local validado en cada capa contra compose stack.
- Pre-launch security script + runbooks + crontab template + Dockerfiles + Caddy + Sentry tuning + backup/restore — todo committed.
- **Próximo paso bloqueante**: contratar VPS + dominio. Luego Capa 9 ~3-4h.
