# Runbook — Observability (Capa 7)

Capa 7 de [DEPLOY_VPS_PLAN.md](../../DEPLOY_VPS_PLAN.md). Cubre lo mínimo para enterarte de fallas antes que el cliente: error tracking, uptime probe externo, disk usage alert. NO Grafana / Loki / Prometheus — overkill para beta cerrada single-VPS.

**Stack final**:
- **Sentry** — backend + frontend errors + performance traces. Tier free hasta 5K events/mes.
- **UptimeRobot O Healthchecks.io** — uptime probe externo. Tier free.
- **disk-alert.sh** — cron hourly, POST a webhook (Slack/Discord) si >80%.
- **Docker logs** — captura nativa stdout, rotación configurada en Capa 5.

---

## 1. Sentry — backend

### Setup inicial

1. Crear cuenta en https://sentry.io (free).
2. Crear proyecto tipo **Django**. Nombre sugerido: `vet-backend`.
3. Copiar el DSN (formato `https://<key>@<orgID>.ingest.us.sentry.io/<projectID>`).
4. Setear en `.env.prod`:

```bash
SENTRY_DSN=https://...@sentry.io/...
SENTRY_TRACES_SAMPLE_RATE=0.05    # 5% (default sano para prod)
SENTRY_RELEASE=                   # vacío OK, mejor setear con git SHA en deploy
```

### Por qué `SENTRY_TRACES_SAMPLE_RATE=0.05`

Cada trace consume cuota Sentry. Free tier = ~10K transacciones/mes. Con 5% sampling y 100 req/min sostenidas:
- 100 req/min × 60 × 24 × 30 = 4.3M req/mes
- 4.3M × 0.05 = 216K traces/mes → excede tier free 22x

Si proyectas >50K req/mes:
- Bajar a 0.02 (2%) o 0.01 (1%)
- O upgrade Team tier ($26/mes)

Para beta cerrada con <1K req/día: `0.05` es seguro.

### Tag de environment

Settings auto-pasa `environment=ENVIRONMENT` al `sentry_sdk.init`. En Sentry UI filtra por `environment:production` para excluir dev/staging.

### Release tag (recomendado para detectar regresiones)

Setear `SENTRY_RELEASE=<sha-corto>` antes del deploy:

```bash
# Wrapper deploy.sh
cd /opt/vet/app
git pull
SENTRY_RELEASE=$(git rev-parse --short HEAD)
sed -i "s/^SENTRY_RELEASE=.*/SENTRY_RELEASE=$SENTRY_RELEASE/" .env.prod
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Sentry agrupa issues por release. Si una regresión aparece exclusivamente en release `abc1234`, sabes qué commit revisar.

### Validar que llega un evento

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend \
  python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('hello from VPS')"
```

Revisar Sentry UI → Issues → debe aparecer "hello from VPS" en <30s.

### Dashboards a configurar (recomendado)

| Dashboard | Métrica | Use |
|-----------|---------|-----|
| **Issues** (default) | error count + frequency | Triage diario |
| **Performance** | p95 transacción `/api/*` | Detectar degradación API |
| **Releases** | issues por release | Vincular regresiones a deploys |
| **Alerts** | nuevo issue P1 → email/Slack | Mismo `ALERT_WEBHOOK` que disk-alert |

Configurar alert: Sentry → Alerts → New Alert Rule:
- Condition: "An issue is first seen"
- Filter: `environment:production` + `level:error`
- Action: Send email + Slack webhook

---

## 2. Sentry — frontend

DSN distinto del backend (proyecto Sentry separado). Setear:

```bash
VITE_SENTRY_DSN=https://<key>@<orgID>.ingest.us.sentry.io/<projectID-frontend>
```

Build args en `frontend/Dockerfile` ya leen `VITE_SENTRY_DSN`. Cambiar el DSN requiere `docker compose build frontend` para re-bake el bundle (build-time, no runtime).

Validación: abrir DevTools en `https://app.tu-dominio.com`, inducir un error JS (`throw new Error('test')` en consola), revisar Sentry UI frontend project.

---

## 3. Uptime probe externo

**Por qué externo**: si el VPS está caído, los crons internos no corren para alertar. Probe externo (ping desde otro DC) detecta caídas reales.

### Opción A — UptimeRobot (recomendado)

Tier free: 50 monitors, ping cada 5min, alerta email/SMS/Slack.

1. Crear cuenta en https://uptimerobot.com.
2. Add New Monitor:
   - Type: **HTTPS**
   - URL: `https://app.tu-dominio.com/api/healthz/`
   - Interval: 5 min
   - Keyword (optional): `ok` (verifica que el body contenga "ok" — no solo 200)
3. Configurar contacts (email primario + Slack webhook recomendado).
4. Probar: ejecutar `docker stop vet-backend-1` en VPS, esperar 6-10min, debe llegar alerta.

### Opción B — Healthchecks.io

Sirve doble propósito: deadman switch para crons (Capa 6) + uptime probe.

Para uptime probe HTTP: configurar como **HTTP Probe** en el dashboard (no "ping" tradicional). Tier free es generoso.

### Probe `/api/healthz/` vs `/api/readyz/`

- `healthz` = proceso vivo, NO toca DB. Probe externo debe usar este.
- `readyz` = DB reachable. Usar para alertas internas (Caddy healthcheck) o monitoreo separado.

Si pones `readyz` en uptime externo: cualquier blip de DB dispara false alarm. Mejor: 2 monitors, uno por endpoint, severidades distintas.

---

## 4. Disk usage alert

Script `scripts/disk-alert.sh` ya integrado al `crontab.example` (cada hora, minuto 15). Monitorea por default:
- `/` (raíz)
- `/var/lib/docker` (containers + images + volumes)
- `/var/backups/vet` (dumps locales)

Para activar alertas, setear `ALERT_WEBHOOK` en el crontab:

```bash
crontab -e
# Cambiar:
15 * * * *  ALERT_THRESHOLD=80 /opt/vet/app/scripts/disk-alert.sh ...
# Por:
15 * * * *  ALERT_THRESHOLD=80 ALERT_WEBHOOK=https://hooks.slack.com/services/... /opt/vet/app/scripts/disk-alert.sh ...
```

Webhook formats soportados:
- **Slack**: `https://hooks.slack.com/services/T.../B.../...` (incoming webhook)
- **Discord**: usar webhook URL con `/slack` sufijo: `https://discord.com/api/webhooks/.../slack`
- **Healthchecks.io fail URL**: `https://hc-ping.com/<uuid>/fail`

Exit codes:
- 0 = todo OK bajo threshold
- 1 = alerta disparada (incluye webhook empty → solo log)
- 2 = webhook POST falló (problema de red o URL malformado)

---

## 5. Docker logs — captura + búsqueda

Rotación configurada en Capa 5 (`/etc/docker/daemon.json` → `max-size: 10m, max-file: 5`). Sin esto los logs llenan disco en días.

### Ver logs en vivo

```bash
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod logs -f --tail=100 backend
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod logs -f --tail=100 caddy
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod logs -f --tail=100 postgres
```

### Grep eventos críticos

Los loggers RBAC y tenant validation emiten JSON estructurado a stdout. Para filtrar:

```bash
# Decisiones RBAC denegadas
docker compose ... logs backend | grep RBAC_DENIED

# Tentativas cross-tenant (Issue de seguridad — investigar TODAS)
docker compose ... logs backend | grep TENANT_MISMATCH_DETECTED

# Failed logins
docker compose ... logs backend | grep LOGIN_FAILED

# Password reset events
docker compose ... logs backend | grep ADMIN_PASSWORD_RESET_ISSUED

# Backup script
tail -100 /var/log/vet-backup.log
```

### Cuándo upgradear a log shipping

Stack actual = `docker logs` + grep manual. Suficiente para 1-5 servicios.

Considerar Loki + Promtail (autohosted) o Logflare/Logtail (managed) cuando:
- Tengas >3 servicios de los que grepear
- Necesites búsqueda full-text histórica (>7 días back)
- Quieras alertas basadas en log patterns (ej. "más de 10 TENANT_MISMATCH_DETECTED en 5min")

Para beta = innecesario.

---

## 6. Sentry CLI release tracking (opcional, post-beta)

Para vincular issues a commits exactos + ver qué archivo / línea cambió entre releases, usar `sentry-cli`:

```bash
# En el script de deploy, post-build:
sentry-cli releases new "$SENTRY_RELEASE"
sentry-cli releases set-commits "$SENTRY_RELEASE" --auto
sentry-cli releases finalize "$SENTRY_RELEASE"
```

Requiere `SENTRY_AUTH_TOKEN` + `SENTRY_ORG` + `SENTRY_PROJECT` envs. Diferido a post-beta — el tag `release` plano ya cubre 80% del valor.

---

## 7. Checklist Capa 7 pre-launch

```
[ ] SENTRY_DSN backend configurado en .env.prod
[ ] VITE_SENTRY_DSN frontend configurado en .env.prod (DSN distinto)
[ ] SENTRY_TRACES_SAMPLE_RATE=0.05 (ajustar según volumen esperado)
[ ] Sentry alert rule: nuevo issue P1 en production → email/Slack
[ ] Test event capturado (sentry_sdk.capture_message("hello"))
[ ] UptimeRobot monitor creado contra /api/healthz/ cada 5min
[ ] Slack/Discord/email contact agregado al monitor
[ ] disk-alert.sh ejecuta sin error (smoke)
[ ] ALERT_WEBHOOK en crontab apuntando a Slack/Discord
[ ] (opcional) Healthchecks.io deadman para los 4 crons (Capa 6)
[ ] Verificado: docker logs backend muestra eventos RBAC structured
[ ] Verificado: log rotation funcional (docker info | grep "Logging Driver")
```

---

## 8. Troubleshooting

| Síntoma | Causa probable | Fix |
|---------|----------------|-----|
| Sentry no recibe events | DSN mal pegado / SENTRY_DSN vacío | `docker compose ... exec backend python -c "from django.conf import settings; import sys; sys.exit(0 if settings else 1)"` y verificar |
| Sentry quota exceeded | TRACES_SAMPLE_RATE muy alto | Bajar a 0.01 o upgrade tier |
| Sentry recibe events pero todos sin source maps frontend | Build no sube sourcemaps a Sentry (deliberadamente — Capa 8 H7) | Para tener stacktrace legible: usar `sentry-cli sourcemaps upload` post-build sin commitear los .map al bundle público |
| UptimeRobot reporta DOWN constantemente | Probe respeta TLS — certificado Caddy aún emitiéndose (ACME challenge falla por DNS no propagado) | `curl -v https://app.tu-dominio.com/` desde tu laptop. Si falla, revisar A record + UFW :80 (ACME HTTP-01) |
| disk-alert dispara con `/var/lib/docker` >80% | Container images viejas + volumes huérfanos | `docker system prune -a --volumes` (CUIDADO: borra unused — confirmar primero con `--dry-run`) |
| backend logs muestran tracebacks repetidos sin que Sentry los agrupe | release tag faltante | Verificar `SENTRY_RELEASE` en `.env.prod` y rebootear backend |

---

## Siguiente

Capa 8 — pre-launch security review (auditoría completa antes de invitar usuarios reales). NO requiere VPS, todo se valida contra compose local + bundle build.
