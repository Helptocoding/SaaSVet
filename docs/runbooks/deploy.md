# Runbook: Despliegue (Sistema + Landing)

**Arquitectura:** dos repos **independientes**, dos mecanismos de deploy distintos,
sobre el mismo VPS Hetzner (`deploy@…`, host `saaslyvet-prod-01`).

| Componente | Repo | Dominio | Cómo se sirve |
|---|---|---|---|
| **Sistema (SaaS)** | `SaaSVet` (`Helptocoding/SaaSVet`) | `app.saaslyvet.com` | Docker Compose: backend (Django/gunicorn) + frontend SPA (React, nginx) detrás de Caddy |
| **Landing** | `SaaSVet-Landing` (`Helptocoding/LandingSaaS`) | `saaslyvet.com` + `www` | Astro **estático**; Caddy del SaaS sirve `frontend/dist` vía bind-mount RO (deuda C8) |

> **No se mezclan.** Un deploy del sistema NO actualiza la landing y viceversa.
> Son repos, branches y comandos separados. Se pueden desplegar en cualquier orden.

Rutas en el VPS:
- Sistema: `~/apps/SaaSVet` (= `/home/deploy/apps/SaaSVet`)
- Landing: `/home/deploy/apps/SaaSVet-Landing`

---

## A) Desplegar el SISTEMA (backend o SPA de la app)

```bash
# 1) En tu máquina — push al branch que despliega el VPS
git push origin develop

# 2) En el VPS
cd ~/apps/SaaSVet
bash scripts/deploy.sh
```

`deploy.sh` hace todo, de forma segura:
- `git pull --ff-only` (avanza al tip del branch)
- snapshot pre-deploy de la DB
- exporta `IMAGE_TAG=<sha>` y **construye** las imágenes `vet-backend` / `vet-frontend`
- `up -d` (recrea contenedores; recrea Caddy **solo si** cambió `infra/Caddyfile`/compose/`DJANGO_ADMIN_URL`)
- migraciones + `collectstatic` + `seed_permissions`
- **health gate** + probe externo a `/api/healthz/`

### Verificación
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
curl -s https://app.saaslyvet.com/api/healthz/      # {"status":"ok"}
git status --porcelain                              # vacío
```

---

## B) Desplegar la LANDING

`deploy.sh` **NO toca la landing.** Es Astro estático y `frontend/dist` está
**gitignored → se construye en el VPS**. Caddy sirve ese `dist` en vivo (no hay que
reiniciar Caddy ni `docker compose`).

**Branch:** producción sirve `main`. El trabajo va en `feature/migration-astro` y se
promueve a `main` por **Pull Request** (como el PR #3).

```bash
# 1) En tu máquina — push del branch de trabajo y merge a main vía PR
git push origin feature/migration-astro
#    → abrir PR feature/migration-astro → main en GitHub y mergear

# 2) En el VPS — traer main y rebuild del estático
cd /home/deploy/apps/SaaSVet-Landing
git pull                       # debe estar en branch main
cd frontend
npm ci                         # instala deps (package-lock.json)
npm run build                  # = astro build → regenera frontend/dist (output static)
```

Caddy sirve el nuevo `dist` **al instante** (lee de disco por request). **Cero downtime,
sin reiniciar nada.**

> **Gotcha:** si haces `git pull` pero **no** corres `npm run build`, la landing NO
> cambia — Caddy sigue sirviendo el `dist` viejo. El build es lo que actualiza lo servido.

### Verificación
```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://www.saaslyvet.com/
curl -sS -o /dev/null -w "%{http_code}\n" https://saaslyvet.com/
```

---

## Reglas duras (no romper)

1. **Nunca recrear `caddy`/`backend` a mano sin `IMAGE_TAG`.** Un
   `docker compose up -d --force-recreate <svc>` pelado cae a `${IMAGE_TAG:-latest}`
   = imagen vieja → **degrada producción** (bug real 2026-06-26). Usa `bash scripts/deploy.sh`
   o `IMAGE_TAG=<sha> docker compose … up -d`.
2. **Secretos solo en `.env.prod`** (gitignored, en el VPS). Nunca commitear `.env.prod`
   ni el slug `DJANGO_ADMIN_URL`.
3. **Cambios de infra** (`infra/Caddyfile`, compose, `DJANGO_ADMIN_URL`) van por el repo
   `SaaSVet` + `deploy.sh`. No editar a mano en el VPS (genera drift → `git pull --ff-only`
   falla y obliga a `git stash`).
4. **El SPA del SaaS ≠ la landing.** `deploy.sh` reconstruye el SPA de `app.saaslyvet.com`,
   nunca la landing.
5. **La revocación por versión de sesión solo es efectiva sin instancias antiguas**
   (ADR p65, riesgo R4). Una instancia con el código anterior no compara la versión de
   sesión: mientras reciba tráfico, un token emitido antes de desactivar, reactivar,
   restablecer o cambiar una contraseña sigue sirviendo en ella. El primer despliegue que
   incluye p65, y cualquiera que toque `apps/core/authentication.py`, solo se da por
   terminado cuando ya ningún contenedor del backend anterior recibe tráfico
   (`docker compose … ps` muestra únicamente contenedores con el `IMAGE_TAG` nuevo). No hace
   falta repetir revocaciones hechas durante el relevo: la versión ya quedó incrementada en
   la base y se aplica en cuanto solo quedan instancias nuevas.

---

## Resumen

| Cambié… | Comando |
|---|---|
| Backend o SPA de la app | `cd ~/apps/SaaSVet && bash scripts/deploy.sh` |
| Landing | push → PR a `main`; en VPS: `cd …/SaaSVet-Landing && git pull && cd frontend && npm ci && npm run build` |
| Ambos | los dos flujos, por separado (orden indiferente) |

> Deuda relacionada: el acoplamiento "Caddy del SaaS sirve la landing" está registrado
> en [`docs/deuda/fase4-prioridad-baja.md`](../deuda/fase4-prioridad-baja.md) → **C8**
> (criterio de desacople futuro).
