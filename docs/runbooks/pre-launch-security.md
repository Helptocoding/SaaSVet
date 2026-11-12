# Runbook — Pre-Launch Security Review (Capa 8)

Capa 8 de [DEPLOY_VPS_PLAN.md](../../DEPLOY_VPS_PLAN.md). Auditoría completa antes de invitar usuarios reales. Bloquea el go-live si cualquier BLOCKER no pasa.

**Cuándo correr**:
1. Una vez antes de cambiar DNS al VPS (gate de launch).
2. Después de cada cambio significativo de infra (.env, settings, Caddyfile).
3. Como verificación post-disaster recovery (restore desde dump → re-run).

**Tiempo**: 30-60 min auditoría + tiempo de fixes detectados.

---

## 1. Script de validación automática

`scripts/pre-launch-security-check.sh` ejecuta 12 categorías de checks contra:
- `.env.prod` en disco
- `infra/Caddyfile`
- `.gitignore`
- containers running (backend + frontend bundle)

```bash
ssh deploy@<VPS_IP>
cd /opt/vet/app
./scripts/pre-launch-security-check.sh
```

Exit codes:
- **0** — todo pasa, go-live aprobado
- **1** — al menos 1 BLOCKER (no launch)
- **2** — solo HIGH/MEDIUM (review + decide)

Categorías cubiertas por el script:

| # | Categoría | Severidad |
|---|-----------|-----------|
| 1 | `.env.prod` existe + chmod 600 + owner deploy | BLOCKER / MEDIUM |
| 2 | Required env vars presentes (SECRET_KEY, DATABASE_URL, etc.) | BLOCKER |
| 3 | Production-mode flags (DEBUG=False, SSL_REDIRECT, HSTS, ALLOW_LEGACY_ID_LOOKUP=False) | BLOCKER |
| 4 | SECRET_KEY length >= 50 + sin pattern placeholder | BLOCKER |
| 5 | POSTGRES_PASSWORD length >= 20 + sin pattern obvio débil | BLOCKER |
| 6 | ALLOWED_HOSTS / CORS / CSRF sin wildcard `*` + sin http:// | BLOCKER / HIGH |
| 7 | DJANGO_SUPERUSER_* NO presente en `.env.prod` | BLOCKER |
| 8 | Sin stray `backend/.env` / `frontend/.env` en repo | BLOCKER |
| 9 | Bundle frontend: 0 `.map`, sin secret patterns AWS/Stripe/Slack/GH, sin http:// API URL | BLOCKER / HIGH |
| 10 | DEBUG=False verify: 404 response sin traceback | BLOCKER |
| 11 | Caddyfile `/admin/` IP allow-list status | HIGH |
| 12 | `.gitignore` cubre `.env.prod` | BLOCKER |

---

## 2. Checks manuales adicionales (no automatizables)

Lo que el script NO valida — requiere juicio humano:

### 2.1 — DNS + TLS

```bash
# Desde TU laptop (no desde el VPS):
dig +short app.tu-dominio.com         # debe responder IP del VPS
curl -I https://app.tu-dominio.com/api/healthz/  # 200 + cert válido (sin -k)

# Verificar cert no expira en <30 días (Caddy auto-renueva en 30d, debe ser >60d)
echo | openssl s_client -servername app.tu-dominio.com -connect app.tu-dominio.com:443 2>/dev/null \
  | openssl x509 -noout -dates
```

### 2.2 — Headers de seguridad — SSL Labs / securityheaders.com

```bash
# Desde tu laptop, evaluar la calidad TLS + headers:
curl -s "https://api.ssllabs.com/api/v3/analyze?host=app.tu-dominio.com&publish=off&startNew=on"
# Esperar 2-3min, repetir sin startNew:
curl -s "https://api.ssllabs.com/api/v3/analyze?host=app.tu-dominio.com" | python -m json.tool
# Target: grade A o A+
```

Alternativa visual: https://securityheaders.com (ingresa el dominio, target A+).

### 2.3 — Bundle audit profundo

Aparte de los patterns que detecta el script (AWS/Stripe/Slack/GH), buscar:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T frontend sh -c "
  grep -rE '(api[_-]?key|secret|token|password)' /usr/share/nginx/html/assets 2>/dev/null | head -10
"
```

Esperado: NINGÚN match obvio. Si aparecen matches, son tipicamente: variable names en código (no valores), nombres de campos de formularios. Inspeccionar caso por caso.

### 2.4 — Test E2E manual

Flow completo HTTPS desde laptop con navegador (no curl):

```
1. Visitar https://app.tu-dominio.com
2. Login con admin SaaS (creado con manage.py bootstrap_superuser)
3. Provision org via POST /api/platform/organizations/
4. Login con admin de org recién creada
5. Crear Owner + Pet
6. Crear Appointment status=scheduled
7. Cambiar a status=done (debe auto-crear MedicalRecord + draft Invoice)
8. Agregar service + product al MedicalRecord
9. Cerrar consulta (status=closed)
10. Confirm + pay Invoice
11. Logout
12. Probar refresh token (DevTools → Network → /api/token/refresh/)
13. Probar change-password
14. Logout + login con nueva password
```

Si todo OK = E2E happy path validado en prod-mode con HTTPS real.

### 2.5 — Rate limit verify

Forzar throttle de login para confirmar que limita:

```bash
# 6 logins fallidos seguidos (debe 429 en el 6to):
for i in $(seq 1 6); do
  curl -sS -o /dev/null -w "attempt $i: HTTP %{http_code}\n" \
    -X POST https://app.tu-dominio.com/api/token/ \
    -H "Content-Type: application/json" \
    -d '{"username":"nonexistent","password":"wrong"}'
done
# Esperado: 4-5 con 401, último con 429 (Too Many Requests)
```

### 2.6 — Postgres NO accesible público

```bash
# Desde TU laptop:
nc -zv <VPS_IP> 5432   # debe timeout (UFW + compose sin port mapping)
```

### 2.7 — admin Django

Si dejaste `/admin/` sin IP allow-list (Capa 3 HIGH H4), mitigaciones mínimas:
- Admin tiene **password >=20 chars** + única (no compartida con otras cuentas)
- Sesión Django expira (settings: `SESSION_COOKIE_AGE`)
- Throttle login `5/15min` activo (ya configurado)
- (Recomendado post-beta) 2FA via `django-otp`

---

## 3. Audit de dependencias (CVE scan)

### Backend — pip-audit

```bash
# Local (laptop con venv activo):
pip install pip-audit
pip-audit -r backend/requirements.lock --no-deps
# Esperado: "No known vulnerabilities found"

# Si aparecen CVEs:
#   - Severity LOW/MEDIUM: anotar, ver upstream fix, planear bump
#   - Severity HIGH/CRITICAL: bloquea launch. Bump version + re-test.
```

### Frontend — pnpm audit

```bash
cd frontend
pnpm audit --prod
# Esperado: "No known vulnerabilities"

# Si aparecen:
#   pnpm audit --prod --fix     # intenta auto-fix
#   Si --fix no resuelve: bump manual de la dep afectada
```

### Política

- **CVSS 9.0+** (CRITICAL): bloquea launch, fix en <24h.
- **CVSS 7.0-8.9** (HIGH): fix en <7d, no bloquea beta si no es exploitable en path expuesto.
- **CVSS <7.0**: tracking, fix en siguiente release window.

Audit baseline (2026-05-26): pip-audit + pnpm audit ambos clean (0 CVEs).

---

## 4. Decisiones documentadas — qué NO cubre Capa 8

Diferido a fases siguientes o aceptado como riesgo:

| Item | Status | Razón |
|------|--------|-------|
| **2FA / MFA admin** | DIFERIDO post-beta (Phase 3 ADR p21) | Beta cerrada con pocos usuarios + password floor 12. MFA con TOTP es 2-3 días de trabajo. |
| **WAF (Cloudflare proxy)** | DIFERIDO | Sin tráfico bot esperado. Cloudflare DNS solo cuando empiece a haber abuse. |
| **fail2ban jail para Django LOGIN_FAILED** | DIFERIDO | Throttle DRF (5/15min) ya cubre brute force. fail2ban a nivel firewall es Phase 2 (requiere scrape de docker logs o vols Django). |
| **CSP report-uri** | DIFERIDO | CSP estricta ya enforce. Report endpoint útil para detectar violaciones reales pero requiere infra extra (Report Hub o /api/csp-report endpoint propio). |
| **Subresource Integrity (SRI)** en Google Fonts | DIFERIDO | Fuentes vienen de googleapis.com (CDN confiable). SRI hashes los pondría a cambiar con cada update de fonts. |
| **Hashed deps en requirements.lock** | DIFERIDO | pip-audit warning recomienda `pip-compile --generate-hashes` para supply chain protection. No bloqueante — agregar Phase 2. |
| **Sentry source maps upload + retención privada** | DIFERIDO | Sin .map files públicos en bundle. Para stacktrace legible en Sentry, subir maps via `sentry-cli sourcemaps upload` sin commitearlos al dist. |
| **Penetration test profesional** | DIFERIDO post-launch | Costo $$$. Posterior a beta cuando haya datos reales que justifiquen pentest. |
| **Bug bounty público** | DIFERIDO | Phase 3 (escala). |

---

## 5. Checklist final — el checklist es el script

```bash
ssh deploy@<VPS_IP>
cd /opt/vet/app

# 1. Auto-check
./scripts/pre-launch-security-check.sh
echo "auto-check exit: $?"

# 2. DNS + TLS
dig +short app.tu-dominio.com
curl -I https://app.tu-dominio.com/api/healthz/

# 3. CVE scan local (en laptop con venv):
pip-audit -r backend/requirements.lock --no-deps
cd frontend && pnpm audit --prod

# 4. Bundle audit profundo (en VPS)
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T frontend sh -c \
  "grep -rE '(api[_-]?key|secret|token|password)' /usr/share/nginx/html/assets 2>/dev/null | head -10"

# 5. E2E manual desde navegador (ver §2.4)

# 6. Rate limit smoke (ver §2.5)

# 7. SSL Labs grade (§2.2)
```

Si TODO pasa → DNS flip + invitar primer cliente. Si algo falla → fixear, re-run, no launch hasta exit 0.

---

## 6. Post-launch (primeras 48h)

Después del primer cliente real:

```bash
# Watch errors
tail -f /var/log/vet-cron.log /var/log/vet-backup.log /var/log/vet-anchor.log

# Watch Sentry (refresh dashboard cada 2h)

# Watch UptimeRobot status

# Verificar backups corren OK noche 1
ls -la /var/backups/vet/
# Debe haber 1 dump nuevo. Tamaño > 1KB.

# Si Sentry recibe issue P1:
#   1. Capture screenshot del trace
#   2. SSH a VPS, docker logs --tail 200 backend para correlación
#   3. Si data corruption sospechado: STOP writes (docker stop vet-caddy-1)
#   4. Restore desde último dump confiable (scripts/pg-restore.sh)
#   5. Si UX-breaking: rollback al commit anterior
```

---

## Siguiente

Capa 9 — deploy real al VPS + validación post-launch. Esto integra todo: clone, .env.prod creation, build, release one-shot, superuser bootstrap, smoke E2E, backup primer ciclo. Requiere VPS provisionado + dominio + DNS.
