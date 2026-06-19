# Production Runbook — VeterinariaSaaS (saaslyvet-prod-01)

> Operación de producción para el beta. Pensado para que **alguien sin contexto**
> pueda desplegar, hacer rollback y reconstruir el servidor desde cero.
>
> Para el desastre total (VPS perdido) ver también
> [`runbooks/RUNBOOK-RESTORE.md`](./runbooks/RUNBOOK-RESTORE.md). Para observabilidad
> [`runbooks/observability.md`](./runbooks/observability.md). Pipeline de backups
> [ADR p40](./decisions/2026-06-12-p40-backup-offsite-disaster-recovery.md).

---

## A. Infraestructura

| Cosa | Valor |
|---|---|
| Proveedor | Hetzner Cloud |
| Servidor | `saaslyvet-prod-01`, plan **CX23** |
| SO | Ubuntu 26.04 |
| Usuario operativo | `deploy` (sudo, grupo `docker`) |
| Path de la app (repo) | **`/home/deploy/apps`** |
| Timezone host | **America/Monterrey** (UTC−6) |
| Acceso | SSH por llave (password OFF), root OFF, fail2ban |
| Firewall (UFW) | sólo **22** (SSH), **80** (HTTP), **443** (HTTPS) |
| Docker | Engine 29.6 + Compose v5.1 |

### Qué corre en el VPS (un solo host, Docker Compose)

```
                 Internet
                    │  :80/:443  (único expuesto, vía UFW)
            ┌───────▼────────┐
            │     caddy      │  TLS auto (Let's Encrypt), headers, gzip/zstd
            │  (reverse proxy)│  / → frontend   /api/* , /admin/* → backend
            └───┬────────┬───┘  /static/* → volumen static_files
                │        │
        ┌───────▼──┐  ┌──▼───────┐
        │ frontend │  │ backend  │  gunicorn :8000 (sólo red interna)
        │ nginx:80 │  │ (django) │
        └──────────┘  └──┬───┬───┘
                         │   │
                  ┌──────▼┐ ┌▼─────────┐
                  │postgres│ │  redis   │  (sólo red interna, SIN puerto host)
                  │ :5432  │ │ :6379    │
                  └────────┘ └──────────┘

  release  = contenedor one-shot (migrate + collectstatic + seed) — corre y sale.
  Crons del host (user deploy): pg-backup, flush JWT, métricas, audit, disk-alert,
  restore-drill. Ver scripts/crontab.example.
```

### Puertos: público vs privado

| Servicio | Puerto | Expuesto al exterior |
|---|---|---|
| caddy | 80, 443 (+443/udp HTTP/3) | **SÍ** (único) |
| backend (gunicorn) | 8000 | NO — sólo red `internal`, Caddy hace proxy |
| frontend (nginx) | 80 | NO — sólo red `internal` |
| postgres | 5432 | NO — sin `ports:`, sólo red `internal` |
| redis | 6379 | NO — sin `ports:`, `requirepass` además |

### Volúmenes persistentes (sobreviven restart/redeploy)

| Volumen | Contenido | Si se pierde |
|---|---|---|
| `pgdata` | base de datos Postgres | catástrofe → restaurar de B2 (sección D4) |
| `caddy_data` | cuenta ACME + certificados TLS | re-emisión de cert (ojo rate-limit LE) |
| `static_files` | output de `collectstatic` | se regenera en el próximo `release` |
| `caddy_config` | estado interno de Caddy | se regenera |

> **Nunca** `docker compose down -v` en producción: borra los volúmenes (incluida
> la DB y los certs).

---

## B. Reconstruir desde cero (servidor nuevo, datos nuevos)

> Esto es el **bootstrap de un host nuevo**. Para recuperar **con datos** desde el
> backup de B2 (VPS perdido) seguí [`RUNBOOK-RESTORE.md`](./runbooks/RUNBOOK-RESTORE.md)
> — es el camino de disaster recovery y reusa estos mismos pasos + restore.

### B1. Crear el VPS
Hetzner Cloud → CX23, Ubuntu 26.04. Anotar IPv4.

### B2. Hardening + dependencias
Seguir [`runbooks/vps-hardening.md`](./runbooks/vps-hardening.md) §1–§11: user `deploy`
con sudo + grupo `docker`, SSH keys-only, root OFF, UFW (22/80/443), fail2ban,
Docker + Compose, log rotation, swap, **timezone America/Monterrey**.

Herramientas de backup/restore en el host:
```bash
sudo apt-get update && sudo apt-get install -y age
curl https://rclone.org/install.sh | sudo bash
age --version && rclone version
```

### B3. Clonar el repo
```bash
ssh deploy@<VPS_IP>
mkdir -p /home/deploy/apps
git clone <repo-url> /home/deploy/apps
cd /home/deploy/apps
```

### B4. Configurar `.env.prod`
```bash
cp .env.prod.example .env.prod
nano .env.prod          # rellenar TODO (ver sección F)
chmod 600 .env.prod
```
Reglas mínimas que valida `scripts/pre-launch-security-check.sh`: `DEBUG=False`,
`ENVIRONMENT=production`, `SECRET_KEY` fuerte y fresco, `POSTGRES_PASSWORD` ≥20,
`ALLOW_LEGACY_ID_LOOKUP=False`, sin wildcards en CORS/CSRF/ALLOWED_HOSTS, sin
`DJANGO_SUPERUSER_*` en el env.

### B5. Primer arranque
```bash
cd /home/deploy/apps
# DNS: apuntar el A record del dominio a <VPS_IP> ANTES (Caddy emite el cert al primer hit).

docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
# bootstrap del admin de plataforma (UNA vez, NO en el env):
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py createsuperuser
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

> El **primer** deploy es manual porque aún no hay `.deploy-state` ni una imagen
> previa que apuntar. A partir del segundo, usá `scripts/deploy.sh` (sección C).

### B6. Smoke + seguridad + crons
```bash
curl -fsS https://<dominio>/api/healthz/    # {"status":"ok"}
curl -fsS https://<dominio>/api/readyz/     # {"status":"ready"}
curl -fsS https://<dominio>/api/version/    # {"version":..,"commit":..,"environment":"production"}
bash scripts/pre-launch-security-check.sh   # debe salir 0
crontab scripts/crontab.example && crontab -l
```

---

## Primer deploy desde servidor vacío

> Bootstrap de un host recién provisionado (sin app, sin datos). De aquí en
> adelante los deploys usan `scripts/deploy.sh` (sección C); **este primer arranque
> es manual** por dos cosas que `deploy.sh` no puede cubrir en un servidor vacío:
> no hay imagen previa a la que volver, y no hay base de datos poblada que respaldar.

### 1. Clonar el repo en la ubicación exacta

```bash
ssh deploy@<VPS_IP>
mkdir -p /home/deploy/apps
git clone <repo-url> /home/deploy/apps            # el repo queda EN /home/deploy/apps
cd /home/deploy/apps
ls docker-compose.prod.yml scripts/deploy.sh      # sanity: deben existir
```

El repo vive **directamente** en `/home/deploy/apps` (no en un subdirectorio).
`deploy.sh` deriva su ruta de su propia ubicación → funciona sin importar el path.

### 2. Crear `.env.prod`

```bash
cp .env.prod.example .env.prod
nano .env.prod          # rellenar TODO (ver sección F)
chmod 600 .env.prod
```

### 3. Validaciones ANTES de ejecutar nada

```bash
# a) .env.prod completo y seguro (sin placeholders CHANGE_ME, DEBUG=False, etc.)
bash scripts/pre-launch-security-check.sh         # objetivo: exit 0

# b) DNS del dominio ya apunta al VPS (Caddy emite el cert TLS al primer hit)
dig +short <dominio>                              # debe devolver el IPv4 del VPS

# c) docker + compose disponibles para el user deploy
docker compose version
```
No sigas si (a) reporta BLOCKERs.

### 4. Primer arranque (manual)

```bash
cd /home/deploy/apps
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

$COMPOSE build
$COMPOSE up -d postgres
$COMPOSE ps                       # esperar postgres → (healthy)
$COMPOSE run --rm release         # migrate + collectstatic + seed_permissions
$COMPOSE run --rm backend python manage.py createsuperuser   # admin plataforma, UNA vez
$COMPOSE up -d
```

### 5. Comportamiento esperado del primer deploy

- **No existe imagen previa.** No hay `.deploy-state` ni un tag-SHA anterior en
  disco. Por eso el primer arranque es manual: si más adelante corrieras `deploy.sh`
  como "deploy #1", **no habría rollback automático de imagen** ante un fallo del
  health gate — `deploy.sh` lo detecta, lo informa (`No previous image tag on
  record`) y se detiene para intervención manual. El rollback automático recién
  existe **del deploy #2 en adelante**, cuando ya hay un tag previo registrado.
- **Backup pre-deploy solo si la DB existe.** El snapshot
  (`pre-deploy-backup.sh`) respalda una DB **poblada**. En un servidor vacío, antes
  del primer `release`, la DB no tiene tablas → no hay nada útil que respaldar (y la
  validación `pg_restore --list` daría 0 entradas, que el script trata como error).
  Por eso el primer arranque no pasa por `deploy.sh`. Una vez que `release` creó el
  schema y hay datos, **cada `deploy.sh` siguiente sí toma su snapshot antes de
  migrar** (sección C, paso 5).

> Resumen: **servidor vacío → primer deploy MANUAL** (pasos 1–4). `deploy.sh` toma
> el control desde el segundo deploy, cuando ya hay imagen previa (objetivo de
> rollback) y DB poblada (punto de restore).

### 6. Confirmar que quedó vivo

```bash
cd /home/deploy/apps
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

# a) Todos los servicios en estado healthy
$COMPOSE ps
#    postgres, redis, backend, frontend, caddy → "healthy"; release → exited (0)

# b) Liveness (proceso arriba, no toca DB)
curl -fsS https://<dominio>/api/healthz/     # {"status":"ok"}

# c) Readiness (DB alcanzable)
curl -fsS https://<dominio>/api/readyz/      # {"status":"ready"}

# d) Versión desplegada (commit + environment)
curl -fsS https://<dominio>/api/version/     # {"version":..,"commit":..,"environment":"production"}
```

Vivo = `ps` todos healthy + `healthz` 200 + `readyz` 200 + `version` con
`"environment":"production"`.

> En el primer arranque manual `GIT_SHA` suele estar vacío en `.env.prod` →
> `/api/version/` reporta `"version":"dev"`, `"commit":null`. Es esperado; a partir
> del primer `deploy.sh` el commit queda seteado automáticamente.

---

## C. Deploy normal

Desde el segundo deploy en adelante, **un solo comando** en el VPS:

```bash
cd /home/deploy/apps
bash scripts/deploy.sh            # despliega el HEAD de la rama actual (git pull --ff-only)
# o una referencia concreta:
bash scripts/deploy.sh <git-ref>  # tag / branch / sha
```

### Qué ocurre internamente (orden, con guardas)

1. **Preflight** — verifica compose, `.env.prod`, docker, repo git.
2. **Record** — lee `.deploy-state` → guarda el tag vivo actual (objetivo de rollback).
3. **Update code** — `git pull --ff-only` (o `checkout <ref>`).
4. **SHA** — `git rev-parse --short HEAD` = id del deploy + tag de imagen.
5. **Backup pre-deploy (H1)** — `pre-deploy-backup.sh`: dump local `-Fc`, validado con
   `pg_restore --list`, nombrado `vet-predeploy-<sha>.dump`. **Si falla, ABORTA** (no
   se migra sin punto de restore).
6. **GIT_SHA** — upsert idempotente de `GIT_SHA` + `SENTRY_RELEASE` en `.env.prod`
   (alinea `/api/version` y el release de Sentry con el commit desplegado).
7. **Build** — `IMAGE_TAG=<sha> docker compose build` (etiqueta `vet-backend:<sha>`,
   `vet-frontend:<sha>`).
8. **Release** — `migrate + collectstatic + seed_permissions` (one-shot). Desde aquí
   el schema puede haber avanzado.
9. **Up** — `IMAGE_TAG=<sha> docker compose up -d`.
10. **Health gate** — espera (timeout 120s): todos los servicios `healthy` +
    `/api/readyz` 200 + `/api/version` == `<sha>` (verifica que el código nuevo
    realmente está sirviendo, sin depender de DNS).
11. **Éxito** → persiste `.deploy-state` + prune de imágenes viejas (conserva últimas 3).
    **Fallo** → **rollback automático de imagen** al tag previo (sin rebuild). Si tras el
    rollback sigue mal y ya se migró, **se detiene** e imprime el comando exacto del
    restore de DB (destructivo, con confirmación). La DB **nunca** se restaura sola.

Exit codes de `deploy.sh`: `0` ok · `1` abort en preflight/backup/release · `2`
desplegó mal pero rollback de imagen OK (revisar) · `3` rollback también falló
(intervención manual).

---

## D. Rollback — por caso

Comando de diagnóstico siempre disponible:
```bash
bash scripts/rollback.sh --list   # muestra CURRENT/PREVIOUS, imágenes en disco y snapshots
```

### D1. Frontend o backend roto (deploy malo, SIN problema de datos)
El `health_gate` de `deploy.sh` ya hace rollback de imagen automático. Si querés
revertir a mano (o el problema apareció después):
```bash
bash scripts/rollback.sh                 # vuelve al tag PREVIOUS de .deploy-state
# o a uno específico:
bash scripts/rollback.sh --to <sha>
```
No destructivo: sólo re-apunta `IMAGE_TAG` a una imagen ya construida y `up -d`
(segundos). Los datos no se tocan.

### D2. Migración mala (corrompió schema/datos)
El rollback de imagen **no** alcanza: la DB ya cambió. Restaurá el snapshot
pre-deploy (DESTRUCTIVO, pide confirmación tecleando el nombre de la DB):
```bash
bash scripts/rollback.sh --restore-db /var/backups/vet/vet-predeploy-<sha>.dump
```
Hace: stop backend → termina conexiones → drop+create DB → `pg_restore` del snapshot
→ levanta la app en el tag PREVIOUS (código que coincide con ese schema) → health gate.
Se pierde lo escrito DESPUÉS del snapshot (minutos, lo del deploy fallido).

### D3. Caddy / TLS roto
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=100 caddy
docker compose -f docker-compose.prod.yml --env-file .env.prod restart caddy
```
Si es el cert: verificá A record + UFW :80 abierto (ACME HTTP-01). No borres
`caddy_data` (perderías la cuenta ACME y pegás contra el rate-limit de LE).

### D4. Pérdida completa del servidor
No es rollback, es disaster recovery: seguí
[`RUNBOOK-RESTORE.md`](./runbooks/RUNBOOK-RESTORE.md) (VPS nuevo → restaurar el
`.dump.age` más reciente de B2 con la llave privada age → promover → levantar).
RPO 24h, RTO 1–2h.

---

## E. Backups — dos sistemas, distinto propósito

| | **Backblaze B2** (offsite) | **Pre-deploy dump** (local) |
|---|---|---|
| Propósito | **Disaster recovery** (VPS perdido) | **Rollback rápido** de un deploy malo |
| Script | `scripts/pg-backup.sh` (cron nocturno) | `scripts/pre-deploy-backup.sh` (lo llama `deploy.sh`) |
| Cifrado | sí, **age** (zero-knowledge) antes de salir del host | no — local, mismo trust zone que la DB viva |
| Destino | bucket B2 con Object Lock + lifecycle | `/var/backups/vet/vet-predeploy-<sha>.dump` |
| Validación | `pg_restore --list` + sha256 + manifest | `pg_restore --list` |
| Retención | B2 lifecycle (daily/ + monthly/) | últimas 5 (`PREDEPLOY_KEEP`) |
| Frecuencia | 1×/día (03:00) + restore-drill mensual | 1× por deploy, antes de migrar |
| Llave para restaurar | age **PRIVATE** (offline, nunca en el VPS) | ninguna (plano local) |

> El pre-deploy dump **no reemplaza** a B2 y B2 **no se usa** en cada deploy. Son
> capas distintas: una para "el deploy salió mal hace 2 minutos", otra para "el
> servidor ya no existe".

Backups en acción:
```bash
tail -100 /var/log/vet-backup.log                  # cron nocturno B2
bash scripts/restore-drill.sh                      # prueba restaurabilidad (local plano)
BACKUP_DECRYPTION_KEY=~/age.key bash scripts/restore-drill.sh --from-offsite  # prueba B2 real
```

---

## F. Variables críticas (`.env.prod`)

`.env.prod` vive sólo en el VPS (`chmod 600`, owner `deploy`), git-ignored. Plantilla
completa en `.env.prod.example`.

| Variable | Qué es | Notas |
|---|---|---|
| `GIT_SHA` | commit desplegado | **lo gestiona `deploy.sh`** — no editar a mano. Alimenta `/api/version` + release Sentry. |
| `APP_VERSION` | etiqueta legible | opcional; deriva de `GIT_SHA` en `settings.py` si vacía. |
| `IMAGE_TAG` | tag de imagen a correr | **lo setea `deploy.sh`/`rollback.sh`** por invocación (no persistir). Default compose `latest`. |
| `SECRET_KEY` | clave Django | fresca, ≥50 chars (`python -c "import secrets;print(secrets.token_urlsafe(64))"`). |
| `DATABASE_URL` | conexión Postgres | `postgresql://vet:<pwd>@postgres:5432/veterinaria`; el `<pwd>` debe igualar `POSTGRES_PASSWORD`/`PGPASSWORD`. |
| `REDIS_URL` | cache + throttle login | `redis://:<pwd>@redis:6379/1`; `<pwd>` == `REDIS_PASSWORD`. **Sin esto el backend no arranca en prod.** |
| `SENTRY_DSN` / `VITE_SENTRY_DSN` | error tracking back/front | DSNs distintos. Vacío = Sentry off (degradación silenciosa). |
| `RCLONE_REMOTE` | destino B2 backups | obligatorio en prod; `pg-backup.sh` falla-loud si está vacío. |
| `BACKUP_ENCRYPTION_PUBLIC_KEY` | recipient age (pública) | NO es secreto. La **privada** vive OFFLINE, nunca en el VPS. |
| `DOMAIN` / `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` / `CORS_ALLOWED_ORIGINS` | dominio + seguridad HTTP | `ALLOWED_HOSTS` debe incluir `localhost` (healthcheck interno). Sin wildcards. |

Secretos que **NO** van en `.env.prod`: credenciales del superuser (bootstrap manual),
la App Key de B2 (vive en `~/.config/rclone/rclone.conf`, chmod 600), la llave
**privada** age (offline).

---

## G. Checklist antes del beta

```
[ ] HTTPS: curl -I https://<dominio>/ → 200 + HSTS/CSP presentes; SSL Labs grade A
[ ] /api/healthz/ y /api/readyz/ responden 200 vía dominio público
[ ] /api/version/ reporta el commit correcto (NO "dev") y environment=production
[ ] pre-launch-security-check.sh → exit 0
[ ] Backup B2: pg-backup.sh corrió y subió (tail /var/log/vet-backup.log); deadman pingó
[ ] Restore PROBADO: restore-drill.sh → RESTORE VERIFIED (local) y --from-offsite (B2 real) al menos 1 vez
[ ] Pre-deploy + rollback PROBADOS en staging: deploy.sh OK; rollback.sh vuelve a imagen previa
[ ] Sentry recibe eventos (backend capture_message + error JS frontend) con environment=production
[ ] Crons instalados (crontab -l) — ojo timezone Monterrey vs horarios del template (ver nota abajo)
[ ] Monitor externo (UptimeRobot) contra /api/healthz/ cada 5min + alerta a email/Slack
[ ] Llave privada age respaldada en 2 sitios offline; credencial superuser en gestor de contraseñas
[ ] docker compose ps → todos healthy tras un sudo reboot de prueba (restart: unless-stopped)
```

> **Nota timezone**: el host está en **America/Monterrey** (UTC−6) pero los horarios
> de `scripts/crontab.example` están pensados en UTC. Revisá que las horas de
> backup/métricas caigan donde querés (ej. `0 3 * * *` en Monterrey = 03:00 local,
> no 03:00 UTC). Ajustá el crontab o el plan según tu ventana de baja actividad.

---

## Apéndice — comandos de diagnóstico rápido

```bash
cd /home/deploy/apps
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

$COMPOSE ps                         # estado + health de cada servicio
$COMPOSE logs -f --tail=100 backend # logs en vivo
$COMPOSE logs backend | grep <request_id>   # correlación P1-5 de un error reportado
bash scripts/rollback.sh --list     # estado de deploy + imágenes + snapshots
curl -fsS https://<dominio>/api/version/
```
