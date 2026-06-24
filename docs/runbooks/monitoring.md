# SaaSlyVet — Production Monitoring Runbook

**Estado:** ACTIVO
**Entorno:** Production
**Dominio:** https://app.saaslyvet.com
**Última actualización:** 2026-06

> Relacionados: [`observability.md`](./observability.md) (Sentry/scrub interno),
> [`cron-jobs.md`](./cron-jobs.md) (backups + deadman), [`RUNBOOK-RESTORE.md`](./RUNBOOK-RESTORE.md) (DR).

---

## Objetivo

Estrategia de monitoreo de producción de SaaSlyVet. El objetivo **NO** es
observabilidad enterprise, sino una configuración simple y confiable para una
beta privada:

- Detectar errores reales de usuarios.
- Saber cuándo la aplicación está caída.
- Confirmar que los backups siguen funcionando.
- Poder relacionar errores con versiones desplegadas.
- Mantener la privacidad de la información clínica.

---

## Arquitectura general

```
Usuario
  │
  ▼
React Frontend ───── errores JS ──────────────▶ Sentry (Frontend)
  │
  ▼
Django API ───── exceptions / HTTP 500 ───────▶ Sentry (Backend)
  │
  ▼
GET /api/version/ ◀──── uptime check ────────── Better Stack (Uptime)

Cron backup (pg-backup.sh) ───── success ping ─▶ Healthchecks.io
```

Cada herramienta responde una pregunta distinta:

| Herramienta | Pregunta que responde |
|---|---|
| Sentry | ¿La aplicación **falló**? |
| Better Stack | ¿La aplicación está **viva**? |
| Healthchecks.io | ¿Los procesos programados **siguen corriendo**? |

---

## 1. Sentry — Backend

### Objetivo

Detectar errores inesperados del backend Django:

- HTTP 500
- excepciones no capturadas
- errores en lógica de negocio
- problemas con la base de datos
- errores durante requests

### Stack

Django · Django REST Framework · `sentry-sdk` · `DjangoIntegration`.

### Configuración esperada

```env
SENTRY_DSN=<backend DSN>
ENVIRONMENT=production
SENTRY_RELEASE=<git SHA>     # lo setea scripts/deploy.sh en cada deploy
```

El `release` se conecta con el commit desplegado. Endpoint de correlación:

```
GET /api/version/
{
  "version": "",
  "commit": "abc1234",
  "environment": "production"
}
```

Sentry debe mostrar `release = abc1234` y `environment = production`. Esto permite:

1. Usuario reporta un error.
2. Revisar el evento en Sentry.
3. Obtener el commit exacto (`release`).
4. `git checkout <SHA>` → reproducir / debuggear.

### Privacidad (fail-closed)

SaaSlyVet maneja información sensible (clientes, mascotas, historial médico,
facturación). El scrub (`apps/core/observability.py`, hook `before_send`) es
**fail-closed**.

**NO se envía:**

- request body (notas clínicas, montos, teléfonos, correos)
- JWT (`Authorization`), cookies, headers sensibles

Ejemplos bloqueados: `Authorization: Bearer …`, `Cookie: sessionid=…`,
`owner_phone`, `diagnosis`, notas médicas.

**Sí se conserva** (información técnica para debuggear):

- exception type
- stack trace
- endpoint + método HTTP
- release (SHA) + environment
- user id interno (ej. `User ID 2` — **sin** email, nombre ni teléfono)

> Limitación conocida (ver [`observability.md`](./observability.md)): el scrub
> cubre `request` y `user`; las variables locales del stacktrace NO se scrubean.
> No reintroducir datos sensibles ligándolos a locales en views clínicas.

### Validación realizada

Se creó temporalmente `/api/__sentry_debug__/` (env-gated + auth). Resultado:
`SentryProbeError` recibido correctamente.

- ✅ evento recibido
- ✅ `environment = production`
- ✅ `release` (SHA) correcto
- ✅ stack trace correcto
- ✅ scrub de privacidad funcionando (sin body / Authorization / Cookie)

**El endpoint fue eliminado después de la prueba.**

---

## 2. Sentry — Frontend

### Objetivo

Detectar errores del cliente React: pantalla blanca, componentes rotos, errores
JavaScript, estados inválidos.

### Stack

React · Vite · `@sentry/react` · `ErrorBoundary`.

Captura: excepción, componente afectado (componentStack), stack trace, release.
Ejemplo: `Cannot read property 'name' of undefined` en `ConsultationForm.jsx`.

### ErrorBoundary

Si React falla, el usuario ve una pantalla controlada que incluye:

```
Código de error: <event_id>
```

El usuario reporta ese `event_id` → se busca directamente en Sentry. El `release`
del frontend coincide con el SHA del backend (`deploy.sh` setea `SENTRY_RELEASE`
para ambos; los source maps se suben bajo ese mismo release).

---

## 3. Better Stack — Uptime

### Objetivo

Detectar la caída completa del SaaS. Sentry **NO** puede detectar:

- VPS apagado
- DNS roto
- Caddy caído
- Docker muerto

…porque en esos casos la aplicación ni siquiera alcanza a enviar errores.

### Monitor

| Campo | Valor |
|---|---|
| Nombre | SaaSlyVet Production API |
| URL | `GET https://app.saaslyvet.com/api/version/` |
| Frecuencia | cada 3 minutos |
| Respuesta esperada | HTTP 200 |
| Contenido esperado | `{ "environment": "production" }` |

Detecta: caída del VPS, backend muerto, reverse proxy caído, problemas de HTTPS,
problemas de DNS.

**Alertas:** canal Email.

---

## 4. Healthchecks.io

### Objetivo

Detectar que los backups dejaron de ejecutarse. **No** monitorea la app —
monitorea: ¿el cron terminó exitosamente?

### Flujo

```
cron
  │
  ▼
pg-backup.sh
  ├─ pg_dump
  ├─ validar dump (pg_restore --list)
  ├─ cifrar (age)
  ├─ subir a Backblaze B2
  │
  ▼
Healthchecks ping (solo en éxito total)
```

**Importante:** el ping SOLO ocurre si dump OK + validación OK + cifrado OK +
upload B2 OK. Si algo falla → **no hay ping** → Healthchecks.io alerta.

### Configuración

```env
HEALTHCHECK_URL=https://hc-ping.com/<uuid>
```

Cron: **21:00 America/Monterrey = 03:00 UTC** (ver [`cron-jobs.md`](./cron-jobs.md)).
En Healthchecks.io: Period 1 day, Grace 1 hour.

---

## 5. Qué hacer ante alertas

> En el VPS, los comandos docker corren desde `/home/deploy/apps/SaaSVet` con
> `-f docker-compose.prod.yml --env-file .env.prod`.

### Sentry (Backend) alerta

Revisar: error, `release` (SHA), stack trace, endpoint afectado. Luego:

```bash
git checkout <SHA>     # reproducir el commit exacto desplegado
# investigar / corregir
```

### Better Stack alerta

```bash
ssh deploy@<VPS>
cd /home/deploy/apps/SaaSVet
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
docker compose -f docker-compose.prod.yml --env-file .env.prod logs backend --tail=100
docker compose -f docker-compose.prod.yml --env-file .env.prod logs caddy   --tail=100
```

Verificación rápida externa:

```bash
curl -i https://app.saaslyvet.com/api/healthz/    # liveness
curl -i https://app.saaslyvet.com/api/readyz/     # readiness (DB)
```

### Healthchecks.io alerta

```bash
ssh deploy@<VPS>
tail -100 /var/log/vet-backup.log                 # output del backup + exit code
rclone lsf b2:saaslyvet-prod-backups/daily/ | tail   # confirmar objeto del día en B2
```

Si el backup falló: revisar el exit code en el log (ver `cron-jobs.md` §5 para la
tabla de exit codes de `pg-backup.sh`). Si no corrió: revisar que el cron esté
instalado (`crontab -l`) y que el host/Docker estén vivos.
