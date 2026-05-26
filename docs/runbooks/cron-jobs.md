# Runbook — cron jobs (Capa 6)

Capa 6 de [DEPLOY_VPS_PLAN.md](../../DEPLOY_VPS_PLAN.md). Tareas recurrentes que viven en el host (no en containers persistentes).

**Pre-requisitos**: VPS provisionado per [vps-hardening.md](./vps-hardening.md). Repo clonado en `/opt/vet/app`. `.env.prod` existe + es 600. Stack arriba al menos una vez.

---

## 1. Inventario

| # | Job | Schedule (UTC) | Schedule (MX, GMT-6) | Criticidad |
|---|-----|----------------|----------------------|------------|
| 6.1 | `pg-backup.sh` | 03:00 daily | 21:00 día anterior | **CRÍTICO** — sin esto pierdes datos |
| 6.2 | `flushexpiredtokens` | 04:00 daily | 22:00 día anterior | ALTO — tablas JWT crecen lineales |
| 6.3 | `build_daily_metrics` | 06:30 daily | 00:30 mismo día | MEDIO — analytics dashboards |
| 6.4 | `audit_anchor_integrity` | 06:35 daily | 00:35 mismo día | ALTO — invariantes contables |
| 6.5 | `journalctl --vacuum-time=14d` | 05:00 domingos | 23:00 sábado | BAJO — housekeeping logs |

Total fenómenos diarios: 4 + 1 semanal. Carga insignificante.

---

## 2. Install

> **Warning**: Corre los crons como user `deploy` (NO root). Los crons usan `docker compose` que requiere membership en grupo `docker` (configurado en `vps-hardening.md` §6).

```bash
ssh deploy@<VPS_IP>
cd /opt/vet/app

# Editar paths si tu install difiere de /opt/vet/app:
nano scripts/crontab.example

# Instalar
crontab scripts/crontab.example

# Verificar
crontab -l
```

`crontab -l` debe imprimir las 5 entradas + las vars `SHELL`, `PATH`, `COMPOSE_DIR`, etc.

---

## 3. Logs

Cada job dirige su output a un archivo distinto en `/var/log/`:

| Log | Contenido |
|-----|-----------|
| `/var/log/vet-backup.log` | output pg-backup.sh |
| `/var/log/vet-cron.log` | output flushexpiredtokens + build_daily_metrics + journalctl vacuum |
| `/var/log/vet-anchor.log` | output audit_anchor_integrity (JSON por run, append) |

Crear los logs con perms correctos ANTES del primer disparo (sino cron escribe como `deploy` y los `sudo` van a fallar):

```bash
sudo touch /var/log/vet-backup.log /var/log/vet-cron.log /var/log/vet-anchor.log
sudo chown deploy:deploy /var/log/vet-backup.log /var/log/vet-cron.log /var/log/vet-anchor.log
```

Rotar con `logrotate` (recomendado post-launch — manual cap por ahora):

```bash
sudo tee /etc/logrotate.d/vet > /dev/null <<'EOF'
/var/log/vet-*.log {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF

# Verificar
sudo logrotate -d /etc/logrotate.d/vet     # dry run
```

---

## 4. Verificar disparos

Ubuntu logs cron events a `syslog`. Filtrar:

```bash
sudo grep CRON /var/log/syslog | tail -20
```

Esperado: una línea por disparo, con el comando ejecutado y exit code.

Para ver el OUTPUT del job (no solo "disparado"):

```bash
tail -f /var/log/vet-backup.log
tail -f /var/log/vet-cron.log
tail -f /var/log/vet-anchor.log
```

---

## 5. Forzar disparo manual (testing)

NO ejecutar `pg-backup.sh` 2 veces el mismo día sin necesidad (crea dump duplicado, consume disco). Para testing:

```bash
# Backup manual one-shot
BACKUP_DIR=/tmp/vet-test \
COMPOSE_DIR=/opt/vet/app \
ENV_FILE=/opt/vet/app/.env.prod \
COMPOSE_FILE=/opt/vet/app/docker-compose.prod.yml \
/opt/vet/app/scripts/pg-backup.sh

# JWT cleanup
cd /opt/vet/app && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py flushexpiredtokens

# Snapshot ayer (idempotente, safe re-run)
cd /opt/vet/app && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py build_daily_metrics

# Anchor audit
cd /opt/vet/app && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py audit_anchor_integrity --json
```

Verificar exit codes:
- `pg-backup.sh`: 0 = OK, 1 = precondición, 2 = dump corrupto, 3 = pg_dump falló.
- `flushexpiredtokens`: 0 siempre (idempotente).
- `build_daily_metrics`: 0 = OK, 2 = al menos 1 org falló (revisar logs).
- `audit_anchor_integrity`: 0 = OK, 1 = unresolved provenance, 2 = invariant violation P1.

---

## 6. Alerting — Healthchecks.io (deadman switch)

Sin esto, si los crons **no corren** (host caído, docker daemon murió, disco lleno), no te enteras hasta que el cliente reporta dashboard congelado o falta de datos.

Healthchecks.io tier free: 20 checks, ping HTTP/HTTPS, alerta email/Slack/Discord/Pushover. Suficiente para 4 crons.

### Setup

1. Crear cuenta en https://healthchecks.io (free, sin tarjeta).
2. Crear un check por job (ej. "vet-pg-backup", schedule daily, grace 1h).
3. Copiar el ping URL (formato `https://hc-ping.com/<uuid>`).
4. Editar `/var/spool/cron/crontabs/deploy` (`crontab -e`) y descomentar `HEALTHCHECK_URL=...` líneas O agregar pings inline:

```cron
# Ejemplo: agregar ping al final del backup line
0 3 * * *   /opt/vet/app/scripts/pg-backup.sh && curl -fsS -m 10 https://hc-ping.com/<uuid-backup> > /dev/null
```

Para `pg-backup.sh` el ping ya está integrado: solo exporta `HEALTHCHECK_URL` en el crontab. Hace ping cuando el script termina sin error.

Para los otros, agregar inline el `&& curl ...` o envolver en un wrapper script.

### Alerta cuándo

Cada check tiene su propio schedule + grace en healthchecks.io. Si no recibe ping en `schedule + grace`, dispara alerta. Ej. backup: schedule `1 day`, grace `1h` → si no llega ping en 25h, alerta.

---

## 7. Troubleshooting

| Síntoma | Causa | Fix |
|---------|-------|-----|
| `crontab -l` muestra entradas pero ningún log se actualiza | Cron daemon caído | `sudo systemctl status cron && sudo systemctl restart cron` |
| `permission denied` en log file | Logs creados como root, cron corre como `deploy` | Re-aplicar §3 chown |
| `docker: command not found` en cron output | `PATH` no incluye `/usr/bin` (donde vive docker) | Verificar línea `PATH=` al inicio del crontab |
| backup duplica timestamp | Cron disparó 2x (raro, ej. systemd timer + cron) | `crontab -l | grep pg-backup` debe ser 1 sola línea |
| `build_daily_metrics` exit 2 random | 1 org tiene anchors corruptos | `docker compose ... run --rm backend python manage.py audit_anchor_integrity` para el detalle |
| journalctl vacuum requiere password sudo | sudo NOPASSWD no configurado | `sudo visudo` y agregar `deploy ALL=(ALL) NOPASSWD: /usr/bin/journalctl` (acotado a este binario) |

---

## 8. Decisiones documentadas

### `run --rm backend` vs `exec backend`

Los 3 manage commands usan `docker compose run --rm backend python manage.py X` (spawn fresh container) en vez de `exec backend python manage.py X` (corre dentro del backend ya activo). Justificación:

- **run --rm**: container nuevo cada vez. Aislado de issues del backend running (OOM, conexiones DB stale, etc.). Overhead ~5-10s spawn time. Salida limpia.
- **exec**: usa el backend ya healthy. Sin spawn overhead. Pero si backend está reiniciando o degraded, el cron falla. Y el output va mezclado con gunicorn logs.

Para crons que toleran 5-10s extra y que DEBEN correr a la hora marcada sí o sí, `run --rm` gana. Si después escalas a >100 RPS y el spawn de container empieza a competir por CPU, considera moverlos a `exec`.

`pg-backup.sh` usa `exec -T postgres pg_dump` (NO `run --rm`) — porque el dump debe ir contra el cluster activo, no contra uno nuevo recién booteado sin datos.

### Crons como `deploy`, no como `root`

Mismo principio que el host hardening: nunca operar como root. `deploy` está en grupo `docker` → puede correr `docker compose`. El único cron que usa `sudo` es journalctl vacuum, y eso se restringe via `NOPASSWD` acotado.

### Horarios UTC

Postgres en UTC + Django `TIME_ZONE='UTC'` + host UTC = cero ambigüedad. Convertir a hora MX al planificar:
```
03:00 UTC = 21:00 MX (día anterior)
04:00 UTC = 22:00 MX (día anterior)
06:30 UTC = 00:30 MX
```

Backup a las 21:00 MX = clínicas ya cerradas, baja actividad. Snapshot a las 00:30 MX = día calendario MX cerrado, dataset estable.

---

## 9. Smoke local (sin VPS)

Los 4 commands se pueden ejecutar contra el compose local antes de tocar el VPS:

```bash
cd /path/al/repo
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d backend

# Cada uno individualmente:
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py flushexpiredtokens
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py build_daily_metrics
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py audit_anchor_integrity --json

BACKUP_DIR=/tmp/test bash scripts/pg-backup.sh
```

Validado durante Capa 6 — 4/4 exit 0 contra DB fresca.

---

## Siguiente

Capa 7 (observability — Sentry sample tuning, UptimeRobot/Healthchecks.io HTTP probes, disk alerts). Puede mergearse en cualquier orden con Capa 6 — no hay dependencia entre ellas.
