# P1-6A — Production Deploy Readiness Report

**Fecha:** 2026-06-18
**Modo:** investigación (sin cambios de código/config/scripts)
**Alcance:** auditar el repo para el primer deploy beta en un VPS único.
**Veredicto corto:** el repositorio está **deploy-ready**. No falta código. Lo que falta es *ejecución en un VPS real* + valores de secretos + cuentas externas (todo tarea tuya), y dos mejoras operativas recomendadas antes de invitar usuarios (backup pre-deploy + runbook de rollback).

> **Actualización 15-11-2026:** los huecos de código que señala este informe ya están cubiertos. `scripts/deploy.sh`, `scripts/rollback.sh` y `scripts/pre-deploy-backup.sh` existen desde `6d41e14` (19-06), integrado por el [PR #1](https://github.com/Helptocoding/SaaSVet/pull/1); el procedimiento está en el [runbook de deploy](docs/runbooks/deploy.md). `DEPLOY_VPS_STATUS.md` y `DEPLOY_VPS_PLAN.md`, que este informe cita, se retiraron del árbol en `8886604` (23-10) y quedan en el historial de git. Sigue pendiente lo que el informe asigna al operador: ejecutar el deploy en un VPS real, hoy no accesible.

> **Nota de fidelidad:** `DEPLOY_VPS_STATUS.md` está fechado **2026-05-26** y dice "8/9 capas". Esa foto quedó vieja: desde entonces se agregaron **Redis (P1-1, ADR p41)**, **observabilidad P1-5** (request_id, Sentry release+scrub, `/api/version`) y **backups cifrados age + offsite B2 (ADR p40)**. El estado real es **más avanzado** que lo que reporta ese doc. Conviene refrescarlo (tarea menor, doc-only).

---

## 1. Estado actual

| Área | Estado actual | ¿Listo prod? | Problema / pendiente |
|---|---|---|---|
| **Docker imágenes** | Multi-stage, non-root (`app`), wheels pre-build, `.dockerignore`, healthcheck. Backend `python:3.13-slim`, frontend `node:20→nginx:1.27`. | ✅ Sí | Ninguno bloqueante. |
| **Compose orquestación** | `postgres + redis + release(one-shot) + backend + frontend + caddy`. Red `internal`, postgres/redis/backend/frontend **sin** puertos host, solo Caddy expone 80/443. `depends_on` por health + `service_completed_successfully`. Resource limits. | ✅ Sí | `pgdata` es **named volume**, no bind-mount (decisión consciente; ver Riesgo L1). |
| **Config Django (`settings.py`)** | Fail-fast en prod: `SECRET_KEY` sin default, `REDIS_URL` requerido, `CORS_ALLOWED_ORIGINS` no-vacío. `SECURE_PROXY_SSL_HEADER`, HSTS, cookies secure, `conn_max_age=60`. | ✅ Sí (plantilla) | Necesita **valores reales** en `.env.prod` (tarea tuya). |
| **`.env.prod.example`** | ~190 líneas, **todas** las vars documentadas (Django, DB, Redis, Sentry, source maps, backup B2/age, gunicorn). | ✅ Sí | Es plantilla — hay que copiarla y rellenarla en el VPS. |
| **Reverse proxy + TLS** | Caddy: ACME auto, HSTS, CSP estricta, X-Frame DENY, COOP/CORP, `-Server`, gzip+zstd, `/static/*` directo, logs JSON. | ✅ Sí | `/admin/` sin IP allow-list (bloque comentado; decisión U13 pendiente — aceptable beta). |
| **Estrategia de deploy** | Secuencia manual de 15 pasos documentada (`DEPLOY_VPS_STATUS.md` + `DEPLOY_VPS_PLAN.md` Capa 9). `release.sh` = migrate+collectstatic+seed idempotente. | ⚠️ Parcial | **No hay script de deploy automatizado** ni **runbook de rollback** ni **backup pre-deploy**. (Fase 2/5.) |
| **Base de datos / persistencia** | Named volume `pgdata`, `restart: unless-stopped`, healthcheck `pg_isready`. `pg_trgm` auto-creado (rol `vet` es superuser). | ✅ Sí | Migraciones forward-only sin auto-rollback (ver Riesgo H1). |
| **Backups + DR** | `pg-backup.sh`: dump→validate→sha256+manifest→**age encrypt**→**rclone B2** (daily+monthly)→retención 14d→deadman. Falla-loud en prod sin offsite. `restore-drill.sh` mensual. `pg-restore.sh` (refuse DB viva). | ✅ Sí (código) | Requiere config en VPS (rclone.conf, llaves age, bucket Object Lock). Path **offsite** solo probado a mano, no en el drill cron (Riesgo H3). |
| **Seguridad host** | Runbook `vps-hardening.md` (user `deploy`, SSH keys-only, UFW, fail2ban, unattended-upgrades, Docker log-rotation, swap, UTC). | ✅ Runbook | Ejecución manual pendiente (tarea tuya, día de deploy). |
| **Secretos** | `.env.prod` chmod 600 + gitignored (`.env.prod` + `.env.prod.*`, whitelist `.example`). **gitleaks CI bloqueante**. Superuser fuera de env (bootstrap manual). | ✅ Sí | Enforcement por `pre-launch-security-check.sh` (12 categorías, exit codes). |
| **Observabilidad** | `request_id` end-to-end (middleware + log filter + CORS + propagación). Sentry backend (init+`before_send` scrub+env+release+traces 0.05) y frontend (DSN+source maps hidden+scrub). `/api/version`, `/api/healthz`, `/api/readyz`. `disk-alert.sh`. | ✅ Sí | Monitores externos (UptimeRobot/Healthchecks) = cuentas tuyas. Sentry release necesita `GIT_SHA` por deploy (manual). |
| **CI/CD** | GitHub Actions: backend (tests+migración drift, Postgres 16), frontend (build+Vitest bloqueantes), security (gitleaks bloqueante, pip/pnpm audit advisory). **Solo CI, no CD.** | ✅ CI | No hay CD/deploy automatizado (deferido, ok beta). |

---

## 2. Qué ya está completo (no tocar — funciona)

1. **Imágenes Docker production-grade.** Multi-stage, non-root, sin compiladores en runtime, sin source maps en el bundle (el frontend `find dist -name '*.map' -delete` como safeguard).
2. **Aislamiento de red correcto.** Solo Caddy publica `:80/:443`. Postgres, Redis, backend y frontend son invisibles desde internet (solo red `internal`). Redis con `requirepass` además (defensa en profundidad).
3. **Orden de arranque garantizado.** `postgres healthy → release (migrate/collectstatic/seed) exit 0 → backend`. Un `migrate` fallido **bloquea** el arranque del backend (no sirve una versión a medio migrar).
4. **Fail-fast de config en producción.** Sin `SECRET_KEY` → no arranca. Sin `REDIS_URL` → no arranca (throttle de login se diluiría ×workers). Sin `CORS_ALLOWED_ORIGINS` → no arranca. Esto previene deploys silenciosamente inseguros.
5. **Login throttle fail-closed.** Cache `throttle_login` con `IGNORE_EXCEPTIONS=False`: si Redis cae, se bloquean logins en vez de servirlos sin límite (único lugar donde se sacrifica disponibilidad por seguridad — ADR p41).
6. **Backups con cifrado zero-knowledge.** El dump plano nunca sale del host; solo la copia cifrada con age (llave pública) va a B2. Un atacante con el VPS **no puede** descifrar el histórico (la llave privada vive offline). Validación de integridad (`pg_restore --list` + sha256 manifest) antes de confiar/subir.
7. **Restore probado por código.** `pg-restore.sh` rehúsa tocar la DB viva, verifica checksum contra manifest, imprime row counts. `restore-drill.sh` mensual restaura a DB descartable y corre los audits contables (`audit_anchor_integrity`, `audit_payment_ledger_integrity`) — el "0 errores" del 3-2-1-1-0.
8. **Headers de seguridad + TLS automático** vía Caddy (CSP estricta, HSTS, X-Frame DENY, COOP/CORP). ACME auto-renueva certs; `caddy_data` persiste como named volume (no re-emite en cada restart).
9. **Observabilidad de producción para beta** (P1-5): correlación `request_id` cliente→backend→logs→Sentry, scrubbing de PII clínica/financiera en ambos lados, `/api/version` para saber qué commit corre cuando una clínica reporta un bug.
10. **Quality gates en CI** bloqueantes (tests backend, build+tests frontend, gitleaks). Migración drift check (`makemigrations --check`).
11. **Runbooks operativos completos:** `vps-hardening.md`, `cron-jobs.md`, `observability.md`, `pre-launch-security.md`, `RUNBOOK-RESTORE.md`.
12. **Script de validación pre-launch** (`pre-launch-security-check.sh`): 12 categorías, distingue BLOCKER/HIGH/MEDIUM, exit 0/1/2. Valida perms de `.env.prod`, fuerza de SECRET_KEY/DB password, ausencia de wildcards CORS, `ALLOW_LEGACY_ID_LOOKUP=False`, ausencia de `.map` y de superuser en env.

---

## 3. Qué falta

### 3.1 Falta de código/config en el repo (tarea AGENTE — opcional, no bloqueante para el primer deploy)

| Item | Severidad | Descripción |
|---|---|---|
| **Backup pre-deploy** | HIGH | No existe un paso que tome un dump *antes* de aplicar migraciones. El backup es solo cron nocturno. Un `migrate` destructivo sobre datos reales no tiene punto de retorno inmediato. |
| **Runbook de rollback** | HIGH | No hay procedimiento documentado para revertir un deploy roto (volver a la imagen/commit anterior + qué hacer con migraciones ya aplicadas). |
| **Script de deploy automatizado** | MEDIUM | Hoy es secuencia manual de 15 pasos (riesgo de error humano). Deferido a post-beta conscientemente, pero un `deploy.sh` con health-gate reduce riesgo. |
| **Refrescar `DEPLOY_VPS_STATUS.md`** | LOW | El doc no menciona Redis/P1-5/p40 (quedó viejo). Doc-only. |
| **Contradicción doc `pgdata`** | LOW | El comentario en `docker-compose.prod.yml:38` dice "Capa 4 will switch this to a bind-mount", pero la tabla de decisiones de `DEPLOY_VPS_STATUS.md` decidió **mantener named volume**. Alinear el comentario. |
| **Verificar `sudo` en cron journalctl** | LOW | `crontab.example:99` usa `sudo journalctl --vacuum-time` en cron no-interactivo del user `deploy`. Sin `NOPASSWD` en sudoers para ese comando, fallará silenciosamente. Confirmar que `vps-hardening.md` lo cubre. |

### 3.2 Falta de ejecución / cuentas externas (tarea TUYA — esto es lo que realmente bloquea el go-live)

| Item | Por qué bloquea |
|---|---|
| **VPS contratado** | Sin host no hay deploy. (Vultr HF MX recomendado por latencia MX, o Hetzner CX22 por precio.) |
| **Dominio + DNS A-record → IP del VPS** | Caddy necesita el dominio para emitir el cert TLS (ACME). |
| **Valores en `.env.prod`** | `SECRET_KEY` fresco, password Postgres (>20 chars), password Redis, `DOMAIN`, `ALLOWED_HOSTS`, DSNs de Sentry. El `pre-launch-security-check.sh` los exige. |
| **Cuenta Sentry + 2 proyectos** (vet-backend, vet-frontend) | DSNs para que la observabilidad funcione. Sin esto Sentry queda no-op (degradación silenciosa, aceptable pero ciego). |
| **Backblaze B2: bucket + App Key + Object Lock + lifecycle** | El backup offsite. App Key debe tener write+list+read pero **NO** deleteFiles (ADR p40), para que un VPS comprometido no borre el histórico. |
| **Par de llaves age** | Generar; **llave privada offline** (tu máquina + backup offline), pública en `.env.prod`. Sin la privada nadie restaura — incluido tú. Custodiarla bien. |
| **rclone.conf en el VPS** (chmod 600) | Con la App Key de B2. No va en `.env.prod`. |
| **UptimeRobot + Healthchecks.io** | Monitor HTTPS de `/api/healthz/` + deadman de los crons. |
| **Ejecutar `vps-hardening.md` §1-§11** | SSH keys-only, UFW, fail2ban, Docker log-rotation, swap, UTC. |
| **`createsuperuser` (una vez)** | El admin de plataforma (ADMIN_SAAS). No va en env. **Custodiar la credencial** — sin MFA, perderla = lockout. |
| **Instalar crons** (`crontab scripts/crontab.example`) | Backup, flush JWT, snapshot analytics, audit integridad, disk-alert, restore-drill. |
| **Decisión U13** (`/admin/` hardening) | Dejar como está (beta) vs IP allow-list vs Cloudflare Access. |

---

## 4. Riesgos

### CRITICAL
*Ninguno bloqueante de origen en el código.* El stack arranca limpio en un VPS nuevo siguiendo la secuencia documentada. Los riesgos reales son de **ejecución y custodia de llaves** (abajo), no de código.

### HIGH
- **H1 — Migración destructiva sin red.** No hay backup pre-deploy ni runbook de rollback. Un `migrate` que borre/altere columnas sobre datos reales de clínicas es difícil de revertir. *Mitigación recomendada antes de go-live:* dump manual antes de cada deploy (o paso automatizado) + documentar rollback.
- **H2 — Deploy manual de 15 pasos.** Riesgo de error humano (saltar el `release` one-shot, olvidar `GIT_SHA`, levantar antes de migrar). *Mitigación:* `deploy.sh` con health-gate (Fase 2).
- **H3 — Path de restore offsite probado solo a mano.** El `restore-drill.sh` en cron usa el `.dump` plano local (no necesita llave privada). El camino real de DR (descargar de B2 + descifrar con age) solo se verifica manualmente. La primera DR real podría sorprender. *Mitigación:* correr `restore-drill.sh --from-offsite` desde tu máquina al menos una vez antes de confiar en el offsite.
- **H4 — Custodia de la llave privada age.** Si se pierde, **todo el histórico de backups en B2 es irrecuperable**. Es un single point of failure de DR. *Mitigación:* dos copias offline en lugares distintos.
- **H5 — Superuser único sin recuperación.** No hay MFA ni flujo de recuperación de cuenta de plataforma. Perder esa credencial = lockout del SaaS-admin. *Mitigación:* gestor de contraseñas + respaldo.

### MEDIUM
- **M1 — `/admin/` sin IP allow-list.** Visible desde cualquier IP (solo protegido por auth de sesión Django + throttle). Aceptable para beta cerrada, pero es superficie de ataque. Decisión U13 pendiente.
- **M2 — Volumen de certs (`caddy_data`).** Persiste (named volume), pero un `docker compose down -v` lo borra → re-emisión de certs → riesgo de pegar contra el rate-limit de Let's Encrypt. Documentar "nunca `down -v` en prod".
- **M3 — Frontend independiente de la salud del backend.** El nginx del SPA sirve aunque el backend esté caído → el usuario ve la app pero las llamadas API fallan. UX degradada, no pérdida de datos.
- **M4 — Doc staleness.** `DEPLOY_VPS_STATUS.md` desactualizado puede inducir a creer que falta menos/más de lo real.

### LOW
- **L1 — `pgdata` named volume vs bind-mount.** Contradicción de comentarios (ver 3.1). El named volume funciona bien con el backup vía `docker exec` (no necesita acceso al filesystem del host). Sin impacto funcional; solo claridad doc.
- **L2 — `GIT_SHA` manual por deploy.** Si se olvida, Sentry agrupa todo bajo "unknown release" y `/api/version` reporta `dev`. No rompe nada, degrada trazabilidad.
- **L3 — `sudo` en cron de journalctl.** Puede fallar sin `NOPASSWD` (ver 3.1).

---

## 5. Plan de implementación P1-6B

> Filosofía: primer deploy beta **simple, seguro, recuperable**. Sin Kubernetes, sin microservicios, sin Terraform, sin AWS complejo. Lo mínimo para levantar el VPS y poder dormir tranquilo.

### Fase 1 — Mínimo para levantar el VPS (bloqueante, ~3-4h, mayormente TUYO)
1. **TÚ:** contratar VPS + dominio + DNS A-record.
2. **TÚ:** generar llaves (SSH ed25519, par age) y cuentas (Sentry ×2 proyectos, B2 bucket+App Key, UptimeRobot, Healthchecks.io).
3. **TÚ:** ejecutar `vps-hardening.md` §1-§11.
4. **TÚ:** `git clone`, `cp .env.prod.example .env.prod`, rellenar TODO, `chmod 600`.
5. **TÚ:** secuencia de deploy (`DEPLOY_VPS_STATUS.md` pasos 5-10): build → postgres healthy → `release` one-shot → `createsuperuser` → `up -d` → smoke `curl /api/healthz|readyz|version`.
6. **TÚ:** `./scripts/pre-launch-security-check.sh` → debe exit 0.
7. **TÚ:** instalar crons + crear/permisos de logs.

### Fase 2 — Automatización de deploy (recomendado, post-primer-deploy, AGENTE)
- `deploy.sh`: `git pull` → **dump pre-deploy** → `build` → `release` (gate: exit 0) → `up -d` → health-check (gate) → en fallo, instrucción de rollback. Setea `GIT_SHA` automáticamente.
- Esto convierte H1 + H2 + L2 en un solo comando seguro.

### Fase 3 — Seguridad del servidor (TUYO, día de deploy)
- Verificar UFW (solo 22/80/443), SSH keys-only (root rechazado, password rechazado), fail2ban activo, Docker log-rotation.
- SSL Labs grade A+ (U34). Rate-limit smoke (6 logins fallidos → 429, U36).
- Decisión U13 sobre `/admin/`.

### Fase 4 — Restore real (TUYO + AGENTE doc)
- **TÚ:** correr `restore-drill.sh --from-offsite` desde tu máquina con la llave privada age (cierra H3) — probar el camino completo B2→descifrar→restaurar→audits.
- **AGENTE:** runbook de rollback explícito (cierra H1) si no se hizo en Fase 2.

### Fase 5 — Go-live checklist (TUYO)
- Smoke E2E navegador: login admin SaaS → provisionar org → crear Owner+Pet+Appointment+MedicalRecord+Invoice → cobrar → corte de caja.
- Sentry capta un error inducido. Reboot del VPS → stack revive solo (`restart: unless-stopped`).
- Monitores externos verdes. Primer backup nocturno corre + deadman pingea.
- Custodia confirmada: llave privada age (2 copias offline) + credencial superuser.

---

## 6. Separación de responsabilidades

### AGENTE (cambios de código/config/scripts — todo opcional para el primer deploy, recomendado antes de invitar usuarios)
- `deploy.sh` con backup pre-deploy + health-gate + rollback (Fase 2). **Cierra H1, H2, L2.**
- Runbook de rollback (`docs/runbooks/`) si no se cubre en `deploy.sh`. **Cierra H1.**
- Refrescar `DEPLOY_VPS_STATUS.md` (Redis + P1-5 + p40). Alinear comentario `pgdata` en compose. Verificar/documentar `sudo NOPASSWD` para journalctl. **Doc/LOW.**
- (Cuando des una IP estable) descomentar/parametrizar el bloque `/admin/` IP allow-list en `Caddyfile`. **Cierra M1.**

### TÚ (infra / dominio / cuentas / llaves — esto es lo que de verdad bloquea)
- Contratar VPS + comprar dominio + configurar DNS.
- Generar y **custodiar** llaves: SSH, par age (privada offline ×2), credencial superuser. **Cierra/contiene H4, H5.**
- Crear cuentas: Sentry (2 proyectos), Backblaze B2 (bucket + App Key sin delete + Object Lock + lifecycle), UptimeRobot, Healthchecks.io.
- Rellenar `.env.prod` con valores reales + `chmod 600`.
- Ejecutar `vps-hardening.md`, la secuencia de deploy, `createsuperuser`, instalar crons.
- Correr `restore-drill.sh --from-offsite` una vez (DR real). **Cierra H3.**
- Decisión U13 (`/admin/`). Go-live checklist Fase 5.

---

## Resumen en una pantalla

- **El código está listo.** 8/9 capas del plan VPS hechas y commiteadas, más Redis + P1-5 + backups cifrados agregados después (el STATUS doc subestima el avance).
- **Un VPS limpio puede levantar el sistema** siguiendo la secuencia documentada — arranque ordenado, fail-fast de config, aislamiento de red correcto, TLS automático.
- **No hay riesgos CRITICAL de código.** Los riesgos HIGH son operativos: backup pre-deploy + rollback ausentes, restore offsite no probado end-to-end, y custodia de llaves (age privada + superuser).
- **Lo que falta para go-live es 90% tarea tuya:** VPS, dominio, cuentas, llaves, valores de secretos, ejecución del hardening y la secuencia de deploy.
- **Lo que el agente debería implementar (opcional, recomendado):** `deploy.sh` con backup pre-deploy + rollback, y refrescar la doc. Nada de esto bloquea el primer deploy manual; reduce el riesgo de los siguientes.
