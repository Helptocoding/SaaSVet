# Plan de Deploy VPS — VeterinariaSaaS

> Plan por capas para migrar de Railway a VPS Ubuntu 24.04 + Docker Compose + Caddy + Postgres.
> Cada capa = PR independiente, mergeable, con exit criteria.
> Dependencias estrictas top-down — no saltar orden.

**Contexto**: SaaS veterinario multi-tenant (Django 6 + DRF + React 19 + Postgres). Beta cerrada, primeros usuarios reales. 1 VPS único. NO k8s, NO microservicios, NO Redis/Celery (overengineering para esta etapa).

---

## Índice

- [Capa 0 — Código backend (prep)](#capa-0--código-backend-prep)
- [Capa 1 — Containerización (imágenes)](#capa-1--containerización-imágenes)
- [Capa 2 — Orquestación local (compose)](#capa-2--orquestación-local-compose)
- [Capa 3 — Reverse proxy + TLS](#capa-3--reverse-proxy--tls)
- [Capa 4 — Postgres data layer + backups](#capa-4--postgres-data-layer--backups)
- [Capa 5 — VPS hardening (host Ubuntu)](#capa-5--vps-hardening-host-ubuntu)
- [Capa 6 — Cron jobs / housekeeping](#capa-6--cron-jobs--housekeeping)
- [Capa 7 — Observabilidad](#capa-7--observabilidad)
- [Capa 8 — Pre-launch security review](#capa-8--pre-launch-security-review)
- [Capa 9 — Deploy + validación post-launch](#capa-9--deploy--validación-post-launch)
- [Resumen tiempos](#resumen-tiempos-por-capa)
- [Orden recomendado de PRs](#orden-recomendado-de-prs)

---

## Capa 0 — Código backend (prep)

**Goal**: app lista para vivir en container sin rituals especiales.

| #   | Item                                                                     | Archivo                                                  | Tipo         |
| --- | ------------------------------------------------------------------------ | -------------------------------------------------------- | ------------ |
| 0.1 | Endpoint `/api/healthz/` (liveness)                                      | `apps/core/views.py` + `config/urls.py`                  | BLOCKER B2   |
| 0.2 | Endpoint `/api/readyz/` (DB ping)                                        | mismo                                                    | BLOCKER B2   |
| 0.3 | Quitar `file` handler de `LOGGING` cuando `ENVIRONMENT=production`       | `config/settings.py:286-291`                             | HIGH H1      |
| 0.4 | Refactor `Procfile` — quitar `migrate/collectstatic/seed` del `web:`     | `backend/Procfile` (o eliminar y usar `release.sh`)      | BLOCKER B3   |
| 0.5 | Crear `scripts/release.sh` ejecutable                                    | nuevo                                                    | BLOCKER B3   |
| 0.6 | `psycopg2-binary` → `psycopg[binary]>=3.1`                               | `requirements.txt`                                       | MEDIUM M2    |
| 0.7 | Pin exact (`==`) vía `pip-compile` o manual lock                         | `requirements.lock`                                      | MEDIUM M1    |

**Exit criteria**:
- `curl localhost:8000/api/healthz/` → 200
- `curl localhost:8000/api/readyz/` → 200 con DB up / 503 sin DB
- Tests siguen pasando (294)

**Tiempo**: 2-3h.

### Snippets

```python
# apps/core/views.py
from django.http import JsonResponse
from django.db import connections
from django.db.utils import OperationalError

def healthz(request):
    return JsonResponse({"status": "ok"})

def readyz(request):
    try:
        connections['default'].cursor().execute('SELECT 1')
    except OperationalError:
        return JsonResponse({"status": "db_down"}, status=503)
    return JsonResponse({"status": "ready"})
```

```python
# config/urls.py — agregar
from apps.core.views import healthz, readyz
path('api/healthz/', healthz),
path('api/readyz/',  readyz),
```

```bash
# scripts/release.sh
#!/bin/sh
set -eu
cd /app
echo "[release] migrate..."
python manage.py migrate --no-input
echo "[release] collectstatic..."
python manage.py collectstatic --no-input
echo "[release] seed_permissions..."
python manage.py seed_permissions
echo "[release] done"
```

---

## Capa 1 — Containerización (imágenes)

**Goal**: build determinístico, slim, non-root, sin secretos.

| #   | Item                                                                                          | Archivo |
| --- | --------------------------------------------------------------------------------------------- | ------- |
| 1.1 | `backend/Dockerfile` multi-stage (builder + runtime) non-root `app` user                      | nuevo   |
| 1.2 | `frontend/Dockerfile` (Node 20 build → nginx:alpine static)                                   | nuevo   |
| 1.3 | `backend/.dockerignore` (excluye venv, __pycache__, .env, logs, docs, .claude, test_e2e.py)  | nuevo   |
| 1.4 | `frontend/.dockerignore` (excluye node_modules, dist, .env, __smoke__)                        | nuevo   |
| 1.5 | Verificar imagen final backend <250MB, frontend <50MB                                         | smoke   |
| 1.6 | Verificar `whoami` dentro container ≠ root                                                    | smoke   |
| 1.7 | `infra/nginx-spa.conf` para imagen frontend                                                   | nuevo   |

**Exit criteria**:

```bash
docker build -t vet-backend ./backend && docker run --rm vet-backend whoami    # → app
docker build -t vet-frontend ./frontend
docker image ls | grep vet                                                     # check sizes
```

**Tiempo**: 3-4h.

### `backend/Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- builder ----
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ---- runtime ----
FROM base AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

COPY --chown=app:app . /app
RUN mkdir -p /app/staticfiles && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000"]
```

### `frontend/Dockerfile`

```dockerfile
# ---- builder ----
FROM node:20-alpine AS builder
WORKDIR /app
RUN npm install -g pnpm@9
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
ARG VITE_API_URL
ARG VITE_SENTRY_DSN
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN}
RUN pnpm run build

# ---- runtime: nginx static ----
FROM nginx:1.27-alpine
RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /app/dist /usr/share/nginx/html
COPY infra/nginx-spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### `infra/nginx-spa.conf`

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
    location ~* \.(js|css|woff2|svg|png|jpg|webp)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### `backend/.dockerignore`

```
__pycache__
*.pyc
*.pyo
*.pyd
.Python
venv/
.venv/
.env
.env.*
!.env.example
logs/*.log
.git
.gitignore
.pytest_cache
.coverage
test_e2e.py
*.md
docs/
.claude/
```

### `frontend/.dockerignore`

```
node_modules
dist
.env
.env.*
!.env.example
.git
__smoke__
*.md
.claude/
```

---

## Capa 2 — Orquestación local (compose)

**Goal**: stack arriba en laptop con datos persistentes.

| #   | Item                                                                                  | Archivo  |
| --- | ------------------------------------------------------------------------------------- | -------- |
| 2.1 | `docker-compose.prod.yml` (postgres, release one-shot, backend, frontend, caddy)      | nuevo    |
| 2.2 | Network `internal` bridge, postgres SIN `ports:`                                      | mismo    |
| 2.3 | `depends_on: condition: service_healthy` postgres → backend                           | mismo    |
| 2.4 | `depends_on: condition: service_completed_successfully` release → backend             | mismo    |
| 2.5 | Healthchecks postgres (`pg_isready`) + backend (`/api/healthz/`)                      | mismo    |
| 2.6 | Resource limits memoria por servicio                                                  | mismo    |
| 2.7 | Volumes: `pgdata` bind-mount, `static_files`, `caddy_data/config`                     | mismo    |
| 2.8 | `.env.prod.example` documentando TODAS las vars                                       | nuevo    |

**Exit criteria**:

```bash
cp .env.prod.example .env.prod && nano .env.prod
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
curl -fsS http://localhost/api/healthz/
```

**Tiempo**: 3-4h.

### `docker-compose.prod.yml`

```yaml
name: vet

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - /var/lib/vet/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits: { memory: 1536M }
    networks: [internal]

  release:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: .env.prod
    command: ["/app/scripts/release.sh"]
    depends_on:
      postgres: { condition: service_healthy }
    networks: [internal]
    restart: "no"
    volumes:
      - static_files:/app/staticfiles

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env.prod
    command:
      - gunicorn
      - config.wsgi:application
      - --bind=0.0.0.0:8000
      - --workers=${GUNICORN_WORKERS:-3}
      - --threads=${GUNICORN_THREADS:-2}
      - --timeout=${GUNICORN_TIMEOUT:-60}
      - --max-requests=1000
      - --max-requests-jitter=100
      - --access-logfile=-
      - --error-logfile=-
      - --log-level=info
    depends_on:
      postgres: { condition: service_healthy }
      release:  { condition: service_completed_successfully }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/healthz/').status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    volumes:
      - static_files:/app/staticfiles
    deploy:
      resources:
        limits: { memory: 768M }
    networks: [internal]

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        VITE_API_URL: https://${DOMAIN}/api/
        VITE_SENTRY_DSN: ${FRONTEND_SENTRY_DSN}
    restart: unless-stopped
    networks: [internal]

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infra/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
      - static_files:/srv/static:ro
    depends_on:
      backend:  { condition: service_started }
      frontend: { condition: service_started }
    networks: [internal]

networks:
  internal:
    driver: bridge

volumes:
  static_files:
  caddy_data:
  caddy_config:
```

### `.env.prod.example`

```dotenv
# Django
DEBUG=False
SECRET_KEY=<GENERAR: python -c "import secrets;print(secrets.token_urlsafe(64))">
ENVIRONMENT=production
ALLOWED_HOSTS=app.tu-dominio.com
CSRF_TRUSTED_ORIGINS=https://app.tu-dominio.com
CORS_ALLOWED_ORIGINS=https://app.tu-dominio.com
DOMAIN=app.tu-dominio.com

# Security headers
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=False
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# IDs
ALLOW_LEGACY_ID_LOOKUP=False

# Database
DATABASE_URL=postgresql://vet:CHANGE_ME_STRONG_PASSWORD@postgres:5432/veterinaria
PGUSER=vet
PGPASSWORD=CHANGE_ME_STRONG_PASSWORD
PGDATABASE=veterinaria
PGHOST=postgres
PGPORT=5432

# Postgres container init
POSTGRES_USER=vet
POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD
POSTGRES_DB=veterinaria

# Sentry
SENTRY_DSN=https://...@sentry.io/...
FRONTEND_SENTRY_DSN=https://...@sentry.io/...

# Gunicorn
GUNICORN_WORKERS=3
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=60

# NO incluir: DJANGO_SUPERUSER_USERNAME/PASSWORD (bootstrap manual)
```

---

## Capa 3 — Reverse proxy + TLS

**Goal**: HTTPS, headers seguros, SPA + API por mismo dominio.

| #   | Item                                                                                                | Archivo / sev |
| --- | --------------------------------------------------------------------------------------------------- | ------------- |
| 3.1 | `infra/Caddyfile` (TLS auto, reverse_proxy, headers)                                                | nuevo         |
| 3.2 | Headers: HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy         | mismo         |
| 3.3 | CSP estricta (`script-src 'self'`, fonts whitelist, connect-src sentry)                             | HIGH H3       |
| 3.4 | Compression `encode gzip zstd`                                                                      | mismo         |
| 3.5 | Static Django (`/static/*`) servido por Caddy desde volume `static_files`                           | mismo         |
| 3.6 | `/admin/*` con IP allow-list                                                                        | HIGH H4       |
| 3.7 | Logging Caddy JSON a stdout                                                                         | mismo         |

**Exit criteria** (con dominio real apuntando al VPS):

```bash
curl -I https://app.tu-dominio.com/api/healthz/   # 200 + headers seguros
curl -I https://app.tu-dominio.com/admin/         # 403 si no IP allow-listed
```

**Tiempo**: 2-3h.

### `infra/Caddyfile`

```caddy
{
    email tu-correo@dominio.com
}

app.tu-dominio.com {
    encode gzip zstd

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
        Permissions-Policy "geolocation=(), microphone=(), camera=()"
        Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' https://*.ingest.us.sentry.io; frame-ancestors 'none'; base-uri 'self'"
        -Server
    }

    @admin path /admin/*
    handle @admin {
        # @office_ips remote_ip 1.2.3.4/32
        # NOT @office_ips respond 403
        reverse_proxy backend:8000
    }

    handle_path /static/* {
        root * /srv/static
        file_server
    }

    handle /api/* {
        reverse_proxy backend:8000 {
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Proto {scheme}
            header_up X-Real-IP {remote_host}
        }
    }

    reverse_proxy frontend:80

    log {
        output stdout
        format json
    }
}
```

---

## Capa 4 — Postgres data layer + backups

**Goal**: datos no se pierden. Restore probado.

| #   | Item                                                                            | Sev / archivo  |
| --- | ------------------------------------------------------------------------------- | -------------- |
| 4.1 | Bind-mount `/var/lib/vet/pgdata` con uid:gid correcto (999:999 postgres)        | docker-compose |
| 4.2 | `scripts/pg-backup.sh` — `pg_dump -Fc` diario, retain 14 días local             | nuevo          |
| 4.3 | Upload a B2/R2/S3 vía `rclone` o `aws s3 cp`                                    | mismo script   |
| 4.4 | `scripts/pg-restore.sh` (one-shot manual)                                       | nuevo          |
| 4.5 | **Test restore en VPS staging** — verificar fila count + join clínico-factura   | manual         |
| 4.6 | Healthchecks.io ping al final del backup                                        | BLOCKER B4     |
| 4.7 | `conn_max_age=60` en prod (no 600 — gunicorn workers x conexiones)              | HIGH H5        |
| 4.8 | Documentar `flushexpiredtokens` cron (Capa 6)                                   | runbook        |

**Exit criteria**:

```bash
/opt/vet/app/scripts/pg-backup.sh
docker compose run --rm postgres psql -U vet -d vet_restore_test -c "SELECT COUNT(*) FROM users_user;"
```

**Tiempo**: 4h (incluye restore test).

### `scripts/pg-backup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR=/var/backups/vet
mkdir -p "$OUT_DIR"
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod \
  exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "$OUT_DIR/vet-$TS.dump"
find "$OUT_DIR" -name 'vet-*.dump' -mtime +14 -delete
rclone copy "$OUT_DIR/vet-$TS.dump" b2:vet-backups/  || true
curl -fsS -m 10 --retry 3 https://hc-ping.com/<uuid>  || true
```

---

## Capa 5 — VPS hardening (host Ubuntu)

**Goal**: superficie de ataque mínima en host.

> **Warning**: Item 5.2 (SSH) es IRREVERSIBLE si se corta acceso. Verificar acceso por key en sesión paralela ANTES de desactivar password.

| #   | Item                                                                                          | Sev / cmd     |
| --- | --------------------------------------------------------------------------------------------- | ------------- |
| 5.1 | User `deploy` con sudo, key SSH copiada                                                       | `adduser deploy && usermod -aG sudo deploy` |
| 5.2 | `/etc/ssh/sshd_config`: `PermitRootLogin no`, `PasswordAuthentication no`, `PubkeyAuthentication yes` | LOW L2 |
| 5.3 | UFW: deny incoming default, allow 22/80/443                                                   | LOW L1        |
| 5.4 | `unattended-upgrades` security patches auto                                                   | MEDIUM        |
| 5.5 | `fail2ban` para sshd                                                                          | MEDIUM M10    |
| 5.6 | Docker oficial install + `compose plugin`                                                     | base          |
| 5.7 | `/etc/docker/daemon.json` log rotation 10m × 5 files                                          | HIGH H12      |
| 5.8 | Swap 2GB (si RAM <4GB)                                                                        | base          |
| 5.9 | Timezone host UTC (`timedatectl set-timezone UTC`)                                            | base          |

**Exit criteria**:

```bash
ssh deploy@vps                                            # OK con key
ssh root@vps                                              # rechazado
ssh deploy@vps -o PreferredAuthentications=password       # rechazado
ufw status                                                # active
docker info | grep -i "Logging Driver"                    # json-file con max-size
```

**Tiempo**: 1-2h.

### Comandos provisión

```bash
# 1. User deploy + key SSH
adduser deploy
usermod -aG sudo deploy
mkdir /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys

# 2. SSH hardening (verificar acceso por key en otra terminal ANTES)
# /etc/ssh/sshd_config: PermitRootLogin no, PasswordAuthentication no, PubkeyAuthentication yes
systemctl restart sshd

# 3. Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# 4. Auto-updates + fail2ban
apt update && apt upgrade -y
apt install -y unattended-upgrades fail2ban
dpkg-reconfigure -plow unattended-upgrades

# 5. Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
apt install -y docker-compose-plugin

# 6. Log rotation Docker
cat > /etc/docker/daemon.json <<EOF
{ "log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "5"} }
EOF
systemctl restart docker

# 7. Swap si RAM <4GB
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## Capa 6 — Cron jobs / housekeeping

**Goal**: tablas no crecen, snapshots corren, integridad auditada.

| #   | Cron entry                                                          | Frecuencia        | Severidad        |
| --- | ------------------------------------------------------------------- | ----------------- | ---------------- |
| 6.1 | `pg-backup.sh`                                                      | 03:00 UTC diario  | BLOCKER B4       |
| 6.2 | `manage.py flushexpiredtokens`                                      | 04:00 UTC diario  | BLOCKER B9       |
| 6.3 | `manage.py build_daily_metrics`                                     | 06:30 UTC diario  | HIGH             |
| 6.4 | `manage.py audit_anchor_integrity --json`                           | 06:35 UTC diario  | HIGH             |
| 6.5 | Healthchecks.io ping en cada cron (alerting si falla)               | inline            | HIGH H10 + L3    |
| 6.6 | Renovación TLS — Caddy auto. nginx+certbot necesita systemd timer  | auto/timer        | BLOCKER B5       |
| 6.7 | Cleanup logs host (`journalctl --vacuum-time=14d` weekly)           | semanal           | MEDIUM           |

**Exit criteria**:

```bash
crontab -l | grep -c '^[^#]' # >= 4
# forzar corrida manual de cada uno y verificar exit 0
```

**Tiempo**: 1h.

### Crontab user `deploy`

```cron
0 3 * * *   /opt/vet/app/scripts/pg-backup.sh >> /var/log/vet-backup.log 2>&1
0 4 * * *   cd /opt/vet/app && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py flushexpiredtokens
30 6 * * *  cd /opt/vet/app && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py build_daily_metrics
35 6 * * *  cd /opt/vet/app && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py audit_anchor_integrity --json
```

---

## Capa 7 — Observabilidad

**Goal**: enterarse de fallas antes que el cliente.

| #   | Item                                                                                          | Acción / sev      |
| --- | --------------------------------------------------------------------------------------------- | ----------------- |
| 7.1 | Sentry backend `traces_sample_rate=0.05` en prod                                              | `settings.py:30` HIGH H11 |
| 7.2 | Sentry frontend DSN distinto del backend, build arg `VITE_SENTRY_DSN`                         | `frontend/Dockerfile` |
| 7.3 | UptimeRobot/Healthchecks.io pegándole a `/api/healthz/` cada 5min                             | UI externo HIGH H10 |
| 7.4 | Logs Docker rotados (Capa 5.7) — confirmar `docker logs --tail 100 vet-backend-1` funciona    | smoke             |
| 7.5 | Disk usage alert (cron simple: `df / | awk` + curl webhook si >80%)                           | HIGH H9           |
| 7.6 | Documentar dashboards Sentry: Issues, Performance, Releases                                   | runbook           |
| 7.7 | RBAC events log (`rbac_console`) — confirmar llegan a stdout en container                     | smoke             |

**Exit criteria**: simular falla (tirar postgres) → alerta en email/Slack <10min.

**Tiempo**: 2h.

---

## Capa 8 — Pre-launch security review

**Goal**: cerrar gaps antes de invitar usuarios reales.

| #    | Item                                                                                                 | Severidad   |
| ---- | ---------------------------------------------------------------------------------------------------- | ----------- |
| 8.1  | Generar SECRET_KEY nuevo, NO reusar local                                                            | BLOCKER B6  |
| 8.2  | `.env.prod` con `chmod 600` + owner `deploy:deploy`                                                  | BLOCKER B6  |
| 8.3  | `ALLOW_LEGACY_ID_LOOKUP=False` en `.env.prod`                                                        | BLOCKER B7  |
| 8.4  | Quitar `DJANGO_SUPERUSER_USERNAME/PASSWORD` de `.env.prod` — bootstrap manual `createsuperuser`     | BLOCKER B8  |
| 8.5  | `ENVIRONMENT=production` activa fail-fast CORS check                                                 | base        |
| 8.6  | Verificar `DEBUG=False` con `curl localhost/api/__no_existe__/` → JSON error genérico sin traceback  | smoke       |
| 8.7  | Auditar bundle frontend: `grep -r "VITE_" dist/` — solo URL/DSN públicos                             | HIGH H8     |
| 8.8  | Confirmar `dist/` no contiene `.map` files                                                           | HIGH H7     |
| 8.9  | `pip-audit` + `npm audit` sin CVE críticos abiertos                                                  | LOW L4      |
| 8.10 | DELETE `backend/.env` del host — solo `.env.prod` debe existir en VPS                                | BLOCKER     |
| 8.11 | Rate limit nginx/Caddy en `/api/token/` + `/api/users/change-password/` (Django throttle ya existe) | HIGH H2     |
| 8.12 | DB password strength (>20 chars random)                                                              | BLOCKER     |
| 8.13 | Verificar `/admin/` no expuesto sin restricción                                                      | HIGH H4     |
| 8.14 | Test E2E: login + crear pet + crear invoice + pagar — todo HTTPS                                     | smoke       |

**Exit criteria**: checklist 14/14 ✓. Pen-test ligero (Burp / OWASP ZAP baseline scan).

**Tiempo**: 3-4h.

---

## Capa 9 — Deploy + validación post-launch

**Goal**: stack vivo + monitoreado + recovery probado.

> Secuencia estricta — NO saltar orden. Postgres antes que release antes que backend.

### Secuencia deploy

```bash
# 9.1 Clonar repo en VPS
ssh deploy@vps
mkdir -p /opt/vet && cd /opt/vet
git clone <repo> app && cd app

# 9.2 Crear .env.prod desde plantilla
cp .env.prod.example .env.prod
nano .env.prod             # rellenar TODO
chmod 600 .env.prod

# 9.3 Build imágenes
docker compose -f docker-compose.prod.yml --env-file .env.prod build

# 9.4 Arranca SOLO postgres y espera healthy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod ps   # esperar (healthy)

# 9.5 Corre release one-shot (migrate + collectstatic + seed_permissions)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release

# 9.6 Bootstrap superuser manual (única vez)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py createsuperuser

# 9.7 Levantar resto del stack
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# 9.8 Smoke E2E
curl -fsS https://app.tu-dominio.com/api/healthz/
curl -fsS https://app.tu-dominio.com/api/readyz/
curl -I  https://app.tu-dominio.com/
docker compose logs --tail=50 backend
docker compose logs --tail=50 caddy

# 9.9 Verificar backup corre
/opt/vet/app/scripts/pg-backup.sh
ls -la /var/backups/vet/

# 9.10 Verificar crons activos
crontab -l
```

### Validación funcional

| #   | Validación                                                          | Cómo                          |
| --- | ------------------------------------------------------------------- | ----------------------------- |
| 9.A | Login admin SaaS produce JWT                                        | manual                        |
| 9.B | Provision org + admin vía `/api/platform/organizations/`            | manual                        |
| 9.C | Crear Pet/Owner/Appointment flujo completo                          | manual                        |
| 9.D | Refresh token rota + viejo blacklisted                              | tail logs `USER_PASSWORD_CHANGED` |
| 9.E | Restart VPS — stack revive solo (`restart: unless-stopped`)         | `sudo reboot`                 |
| 9.F | Sentry capta error inducido (forzar 500 vía endpoint test)          | UI Sentry                     |

**Tiempo**: 2-3h primer deploy + 1h validación.

---

## Resumen tiempos por capa

| Capa | Trabajo                  | Tiempo  | Dependencia        |
| ---- | ------------------------ | ------- | ------------------ |
| 0    | Código backend prep      | 2-3h    | —                  |
| 1    | Containerización         | 3-4h    | 0                  |
| 2    | Orquestación compose     | 3-4h    | 1                  |
| 3    | Reverse proxy + TLS      | 2-3h    | 2                  |
| 4    | Postgres + backups       | 4h      | 2                  |
| 5    | VPS hardening            | 1-2h    | — (paralelo)       |
| 6    | Cron / housekeeping      | 1h      | 4, 5               |
| 7    | Observability            | 2h      | 3                  |
| 8    | Security review          | 3-4h    | 1-7                |
| 9    | Deploy + validación      | 3-4h    | 0-8                |

**Total**: ~25-30h trabajo. Distribuido 4-5 días full-time, o 2 semanas part-time.

---

## Orden recomendado de PRs

```
PR1: Capa 0      (código backend, healthchecks, release.sh)        ← merge first
PR2: Capa 1      (Dockerfiles + .dockerignore + nginx-spa.conf)    ← dep PR1
PR3: Capa 2      (compose + .env.prod.example)                     ← dep PR2
PR4: Capa 3      (Caddyfile + headers + CSP)                       ← dep PR3
PR5: Capa 4      (backup/restore scripts + conn_max_age)           ← dep PR3
PR6: Capa 6 + 7  (cron docs + Sentry tuning)                       ← dep PR4, PR5
PR7: docs/runbooks/deploy-vps.md (capas 5 + 8 + 9 como runbook)    ← dep all
```

Capa 5 (host hardening) no es código — runbook en último PR.

---

## Riesgos clasificados (referencia rápida)

### BLOCKER (no deploy sin esto)
- B1 Sin Dockerfile/compose/nginx (Capa 1+2+3)
- B2 Sin healthcheck endpoint (Capa 0)
- B3 Migrate inline en boot del web (Capa 0)
- B4 Sin backups Postgres (Capa 4)
- B5 TLS sin gestionar (Capa 3)
- B6 SECRET_KEY local débil (Capa 8)
- B7 `ALLOW_LEGACY_ID_LOOKUP=True` default (Capa 8)
- B8 `DJANGO_SUPERUSER_PASSWORD` en `.env` (Capa 8)
- B9 JWT blacklist sin cleanup (Capa 6)

### HIGH
- H1 Logger file en container (Capa 0)
- H2 Sin rate limit nginx (Capa 3/8)
- H3 Sin CSP (Capa 3)
- H4 `/admin/` expuesto (Capa 3/8)
- H5 `conn_max_age=600` excesivo (Capa 4)
- H6 Gunicorn workers no configurados (Capa 2)
- H7 Sourcemaps frontend (Capa 8)
- H8 Secretos en bundle VITE_ (Capa 8)
- H9 Disk usage sin monitor (Capa 7)
- H10 Sin uptime monitor externo (Capa 7)
- H11 Sentry sample_rate=0.2 caro (Capa 7)
- H12 Docker logs sin rotation (Capa 5)

### MEDIUM
- M1 requirements sin pin (Capa 0)
- M2 psycopg2-binary → psycopg v3 (Capa 0)
- M3 Sin .dockerignore (Capa 1)
- M4 pnpm-lock build doc (Capa 1)
- M5 CSRF + CORS doc (Capa 8)
- M6 Backup geo-redundancia post-beta
- M7 Postgres healthcheck en compose (Capa 2)
- M8 UID mismatch logs (Capa 0)
- M9 Whitenoise + nginx (Capa 1/3)
- M10 Fail2ban (Capa 5)

### LOW
- L1 UFW (Capa 5)
- L2 SSH keys-only (Capa 5)
- L3 Cron alerting (Capa 6)
- L4 Dependency scan (Capa 8)
- L5 Container exposure (Capa 2)

---

## Diferido post-beta (no bloqueante v1)

- Redis (solo si throttle multi-instance)
- Celery / RQ (sin tareas async fuera de cron)
- PgBouncer (innecesario <50 RPS)
- CDN / Cloudfront
- CI/CD completo (manual `git pull && docker compose up -d --build` ok para empezar)
- Observability stack (Grafana/Loki/Prometheus) — Sentry + docker logs alcanza
- K8s / Nomad / Swarm — overengineering
- MFA / TOTP (ADR p21 diferido)
- WAF Cloudflare proxy (post-beta DDoS gratis)
- Backups geo-redundantes

---

## Arquitectura VPS

```
                    Internet
                       │
              ┌────────▼────────┐
              │   VPS Ubuntu    │  (1 host)
              │     24.04       │
              │                 │
              │  ┌────────────┐ │
              │  │   Caddy    │ │ :80/:443 (TLS auto)
              │  │            │ │ reverse proxy + static SPA + rate limit
              │  └─┬────────┬─┘ │
              │    │        │   │
              │    ▼        ▼   │
              │  /api    /  (SPA dist)
              │    │            │
              │  ┌─▼──────────┐ │
              │  │  backend   │ │ gunicorn :8000 (interno)
              │  │  (django)  │ │
              │  └─┬──────────┘ │
              │    │            │
              │  ┌─▼──────────┐ │
              │  │ postgres   │ │ :5432 (interno, NO expuesto)
              │  │ +volume    │ │ pgdata bind-mount /var/lib/vet/pg
              │  └────────────┘ │
              │                 │
              │  ┌────────────┐ │
              │  │ cron host  │ │ pg-backup, flushexpiredtokens,
              │  └────────────┘ │ build_daily_metrics
              └─────────────────┘
                       │
                       ▼
              S3/B2/R2 backups
              (pg_dump diario)
```

**Sizing mínimo** (beta cerrada, <100 usuarios concurrentes):
- CPU: 2 vCPU
- RAM: 4 GB
- Disco: 40 GB SSD
- Bandwidth: 1 TB/mes

**Proveedores match**: Hetzner CX22 (€4/mes), DigitalOcean Premium AMD 4GB ($24/mo), Vultr HF 2C/4GB ($24).

**Cuándo escalar**:
- Postgres >70% CPU sostenido → host dedicado o managed (Neon/Supabase)
- Gunicorn timeout creciendo → más workers / aumentar RAM
- Disco >70% → cleanup + crecer volume
- >5 deploys/semana molestos → blue-green via 2 backend containers + nginx upstream switch

---

## Estructura final servidor Linux

```
/etc/
├── docker/daemon.json              # log rotation
├── ssh/sshd_config                 # keys-only, no root
└── ufw/                            # 22, 80, 443

/opt/vet/app/                       # git clone aquí
├── .env.prod                       # chmod 600, owner deploy
├── docker-compose.prod.yml
├── backend/
│   ├── Dockerfile
│   ├── .dockerignore
│   └── ...
├── frontend/
│   ├── Dockerfile
│   ├── .dockerignore
│   └── ...
├── infra/
│   ├── Caddyfile
│   └── nginx-spa.conf
└── scripts/
    ├── release.sh
    ├── pg-backup.sh
    └── pg-restore.sh

/var/lib/vet/pgdata/                # Postgres volume bind-mount (chown 999:999)
/var/backups/vet/                   # pg_dump dumps locales (14 días)
/var/log/vet-backup.log             # cron output

/home/deploy/.ssh/authorized_keys   # solo claves SSH
                                    # crontab -e contiene jobs
```
