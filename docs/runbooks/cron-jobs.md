# Runbook — cron jobs (Capa 6)

Capa 6 de [DEPLOY_VPS_PLAN.md](../../DEPLOY_VPS_PLAN.md). Tareas recurrentes que viven en el host (no en containers persistentes).

**Pre-requisitos**: VPS provisionado per [vps-hardening.md](./vps-hardening.md). Repo clonado en `/home/deploy/apps/SaaSVet`. `.env.prod` existe + es 600. Stack arriba al menos una vez.

---

## 1. Inventario

> **Timezone:** el host corre en **America/Monterrey (UTC-6)**. Cron interpreta
> las expresiones en hora **local**, así que la hora de la expresión = hora MX.
> La columna "Equivale UTC" es local + 6h (para correlacionar con logs en UTC).

| # | Job | Cron (local MX) | Equivale UTC | Criticidad |
|---|-----|-----------------|--------------|------------|
| 6.1 | `pg-backup.sh` | `0 21 * * *` | 03:00 diario | **CRÍTICO** — sin esto pierdes datos |
| 6.2 | `flushexpiredtokens` | `0 4 * * *` | 10:00 diario | ALTO — tablas JWT crecen lineales |
| 6.3 | `build_daily_metrics` | `30 6 * * *` | 12:30 diario | MEDIO — analytics dashboards |
| 6.4 | `audit_anchor_integrity` | `35 6 * * *` | 12:35 diario | ALTO — invariantes contables |
| 6.5 | `journalctl --vacuum-time=14d` | `0 5 * * 0` | 11:00 (dom) | BAJO — housekeeping logs |
| 6.6 | `seed_demo_clinic --reset --yes` | `10,40 * * * *` | cada 30 min | MEDIO — demo pública: si falla, datos sucios/rotos (NO afecta clínicas reales, ADR p49) |

`restore-drill.sh` (ADR p40) **NO va por cron** — drill MANUAL mensual desde la
máquina del operador (`--from-offsite` + age private key). Es el único que prueba
la cadena real B2 download + age decrypt + restore. Ver §5.bis.

Total cron: 4 diarios + 1 semanal (+ disk-alert horario, ver §abajo). Carga insignificante.

---

## 2. Install

> **Warning**: Corre los crons como user `deploy` (NO root). Los crons usan `docker compose` que requiere membership en grupo `docker` (configurado en `vps-hardening.md` §6).

```bash
ssh deploy@<VPS_IP>
cd /home/deploy/apps/SaaSVet

# Editar paths si tu install difiere de /home/deploy/apps/SaaSVet:
nano scripts/crontab.example

# Instalar
crontab scripts/crontab.example

# Verificar
crontab -l
```

`crontab -l` debe imprimir las líneas de jobs + las vars `SHELL`, `PATH`, `COMPOSE_DIR`, etc.

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
COMPOSE_DIR=/home/deploy/apps/SaaSVet \
ENV_FILE=/home/deploy/apps/SaaSVet/.env.prod \
COMPOSE_FILE=/home/deploy/apps/SaaSVet/docker-compose.prod.yml \
/home/deploy/apps/SaaSVet/scripts/pg-backup.sh

# JWT cleanup
cd /home/deploy/apps/SaaSVet && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps backend python manage.py flushexpiredtokens

# Snapshot ayer (idempotente, safe re-run)
cd /home/deploy/apps/SaaSVet && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps backend python manage.py build_daily_metrics

# Anchor audit
cd /home/deploy/apps/SaaSVet && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps backend python manage.py audit_anchor_integrity --json
```

Verificar exit codes:
- `pg-backup.sh` (ADR p40): 0 = OK | 1 = precondición | 2 = dump corrupto |
  3 = pg_dump falló | 4 = validación `pg_restore --list` falló | 5 = cifrado/rclone
  no disponible | 6 = offsite mal configurado o falló (solo producción).
- `restore-drill.sh` (ADR p40): 0 = RESTORE VERIFIED | 1 = precondición |
  2 = restore falló | 3 = health check falló. Corre con el `.dump` plano local
  (no necesita private key). Para probar el path cifrado/offsite:
  `BACKUP_DECRYPTION_KEY=~/keys/age.key scripts/restore-drill.sh --from-offsite`.
- `flushexpiredtokens`: 0 siempre (idempotente).
- `build_daily_metrics`: 0 = OK, 2 = al menos 1 org falló (revisar logs).
- `audit_anchor_integrity`: 0 = OK, 1 = unresolved provenance, 2 = invariant violation P1.
- `seed_demo_clinic --reset` (ADR p49): 0 = OK **o** skip por advisory lock |
  != 0 = fallo de validación/integridad (ROLLBACK, demo intacta). Solo exit 0
  pinguea el deadman `HEALTHCHECK_DEMO_RESET_URL`. Offset a :10/:40 para no
  coincidir con backup/snapshot/anchor. Recuperación: ADR p49 §12.

---

## 5.bis Restore drill — solo MANUAL offsite (ADR p40, decisión beta 2026-06-20)

**El restore drill NO corre por cron.** En beta solo se hace **manual, mensual,
desde la máquina del operador** con la age **private key** y `--from-offsite`.

| Qué prueba | Cómo | Cuándo |
|---|---|---|
| `B2 download → age decrypt → restore → auditorías` (la cadena de desastre REAL) | a mano con la age **private key** + `--from-offsite` | **1 vez al mes, a mano** |

Por qué NO el drill local automático por cron:

- El drill local (sin `--from-offsite`) usa el `.dump` **plano local**, así que
  **NO** prueba B2 ni el descifrado `age` — justo lo que puede fallar en un
  desastre real (key perdida/corrupta, `.age` subido mal).
- Crea una DB temporal en el postgres de **prod** y levanta un container backend
  para las auditorías → partes móviles en producción que no conviene desatender
  en beta.
- Conclusión: poco valor + riesgo en prod. Mejor un único drill **manual** que sí
  ejerce la cadena completa.

> ⚠️ **Un backup sin restore probado no es backup.** Si la private key se perdió,
> se corrompió, o el `.age` subió mal, solo te enteras el día del desastre. Por
> eso el drill offsite manual es **obligatorio**, no opcional.

### Prueba offsite mensual (hazla tú, desde tu máquina con la private key)

```bash
# En tu máquina (NO el VPS), con la age private key montada temporalmente.
# Requiere rclone configurado + acceso al postgres del stack (local o VPS).
cd /home/deploy/apps/SaaSVet   # o el repo local

BACKUP_DECRYPTION_KEY=/ruta/segura/age.key \
RCLONE_REMOTE=b2:saaslyvet-prod-backups \
  scripts/restore-drill.sh --from-offsite
# → baja el último vet-*.dump.age de daily/, lo descifra con tu private key,
#   restaura a una DB descartable, corre las auditorías → RESTORE VERIFIED.
```

Si esto NO termina en `RESTORE VERIFIED`, tienes un incidente de DR latente
(key, cifrado o upload roto) — resuélvelo antes del siguiente backup. Anota la
fecha del último drill offsite exitoso; si pasan >35 días, es deuda P0.

---

## 6. Alerting — Healthchecks.io (deadman switch)

Sin esto, si los crons **no corren** (host caído, docker daemon murió, disco lleno), no te enteras hasta que el cliente reporta dashboard congelado o falta de datos.

Healthchecks.io tier free: 20 checks, ping HTTP/HTTPS, alerta email/Slack/Discord/Pushover. Suficiente para 4 crons.

> **É-F0**: además de los crons, el **worker del agente WhatsApp** tiene su
> propio deadman ("vet-agent-worker", period ~5 min, grace 5 min) — no es un
> cron sino un loop permanente que pinguea `HEALTHCHECK_AGENT_WORKER_URL`
> cada ~60 ciclos sanos. Ver `docs/runbooks/agent-whatsapp.md` §4.

### Setup

1. Crear cuenta en https://healthchecks.io (free, sin tarjeta).
2. Crear un check por job (ej. "vet-pg-backup", schedule daily, grace 1h).
3. Copiar el ping URL (formato `https://hc-ping.com/<uuid>`).
4. Editar `/var/spool/cron/crontabs/deploy` (`crontab -e`) y descomentar `HEALTHCHECK_URL=...` líneas O agregar pings inline:

```cron
# Ejemplo: agregar ping al final del backup line
0 21 * * *  /home/deploy/apps/SaaSVet/scripts/pg-backup.sh && curl -fsS -m 10 https://hc-ping.com/<uuid-backup> > /dev/null
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
| `build_daily_metrics` exit 2 random | 1 org tiene anchors corruptos | `docker compose ... run --rm --no-deps backend python manage.py audit_anchor_integrity` para el detalle |
| journalctl vacuum requiere password sudo | sudo NOPASSWD no configurado | `sudo visudo` y agregar `deploy ALL=(ALL) NOPASSWD: /usr/bin/journalctl` (acotado a este binario) |

---

## 8. Decisiones documentadas

### `run --rm backend` vs `exec backend`

Los crons pasan `--no-deps`: `backend` depende de `release`, y sin el flag cada corrida relanzaría `migrate`, `collectstatic` y `seed_permissions` contra la base viva. Con el flag no se arranca ningún servicio; si postgres está caído, el comando falla con exit distinto de cero y el cron lo registra.

Los 3 manage commands usan `docker compose run --rm --no-deps backend python manage.py X` (spawn fresh container) en vez de `exec backend python manage.py X` (corre dentro del backend ya activo). Justificación:

- **run --rm**: container nuevo cada vez. Aislado de issues del backend running (OOM, conexiones DB stale, etc.). Overhead ~5-10s spawn time. Salida limpia.
- **exec**: usa el backend ya healthy. Sin spawn overhead. Pero si backend está reiniciando o degraded, el cron falla. Y el output va mezclado con gunicorn logs.

Para crons que toleran 5-10s extra y que DEBEN correr a la hora marcada sí o sí, `run --rm` gana. Si después escalas a >100 RPS y el spawn de container empieza a competir por CPU, considera moverlos a `exec`.

`pg-backup.sh` usa `exec -T postgres pg_dump` (NO `run --rm`) — porque el dump debe ir contra el cluster activo, no contra uno nuevo recién booteado sin datos.

### Crons como `deploy`, no como `root`

Mismo principio que el host hardening: nunca operar como root. `deploy` está en grupo `docker` → puede correr `docker compose`. El único cron que usa `sudo` es journalctl vacuum, y eso se restringe via `NOPASSWD` acotado.

### Horarios — host en America/Monterrey (UTC-6)

Postgres en UTC + Django `TIME_ZONE='UTC'`, pero el **host (y por lo tanto cron)
corre en America/Monterrey**. Las expresiones cron se interpretan en hora LOCAL
de Monterrey. Conversión local → UTC = **+6h**:
```
0 21 * * *  = 21:00 MX = 03:00 UTC   (backup)
0 4  * * *  = 04:00 MX = 10:00 UTC   (jwt cleanup)
30 6 * * *  = 06:30 MX = 12:30 UTC   (snapshot)
35 6 * * *  = 06:35 MX = 12:35 UTC   (anchor audit)
```

Backup a las 21:00 MX = clínicas ya cerradas, baja actividad. Snapshot a las
06:30 MX = ya pasó la medianoche local, el día calendario MX anterior está
cerrado y el dataset es estable.

---

## 9. Smoke local (sin VPS)

Los 4 commands se pueden ejecutar contra el compose local antes de tocar el VPS:

```bash
cd /path/al/repo
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d backend

# Cada uno individualmente:
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps backend python manage.py flushexpiredtokens
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps backend python manage.py build_daily_metrics
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps backend python manage.py audit_anchor_integrity --json

BACKUP_DIR=/tmp/test bash scripts/pg-backup.sh
```

Validado durante Capa 6 — 4/4 exit 0 contra DB fresca.

---

## Siguiente

Capa 7 (observability — Sentry sample tuning, UptimeRobot/Healthchecks.io HTTP probes, disk alerts). Puede mergearse en cualquier orden con Capa 6 — no hay dependencia entre ellas.
