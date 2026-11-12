# Plan de rotación de secretos — auditoría de exposición histórica (P1-6C)

**Fecha de auditoría**: 2026-06-19
**Autor**: auditoría de seguridad (security-auditor) + verificación forense Git
**Estado**: pendiente de ejecución — **NO bloquea el deploy**, pero la rotación obligatoria
debe completarse **antes** de exponer el VPS de producción a Internet.
**Alcance**: solo auditoría + documentación. No se modificó código, no se reescribió
history, no se ejecutó BFG/filter-repo, no se hizo force-push, no se rotó ningún secreto.

---

## 1. Contexto

Preparando el primer deploy a VPS self-hosted (migración desde Railway). El repositorio
es **privado** (GitHub, `felipeddiaz`), pero durante las etapas iniciales del proyecto
(era Railway) se commitearon archivos `.env` **reales** con secretos en plaintext.

**Decisión deliberada**: NO limpiar history ahora con BFG / `git filter-repo`, porque:

- puede romper ramas y PRs abiertos,
- requiere force-push,
- estamos antes del primer deploy (prioridad: salir a prod, no reescribir history),
- la **mitigación principal es rotar los secretos**, no borrar la evidencia.

La limpieza de history queda documentada como **hardening futuro** (§7).

---

## 2. Qué ocurrió (forense Git verificado)

Dos archivos `.env` reales (no plantillas) estuvieron commiteados con secretos en plaintext:

| Archivo | Añadido | Eliminado | Ventana de exposición |
|---|---|---|---|
| `backend/.env` | `71f306a` (2026-04-19, "First commit") | `28eac54` (2026-05-07, "Version 1.1.2") | ~18 días |
| `frontend/.env` | `71f306a` (2026-04-19) | `28eac54` (2026-05-07) | ~18 días |

`backend/.env` además se modificó en `86e2db2` ("deploy"), `6424e48` ("env db railway")
y `f9076f8` ("create admin saas") — ahí entraron las credenciales de Postgres de Railway
y las del superusuario.

**Estado actual del working tree (verificado limpio):**

- Archivos `.env` rastreados hoy: **solo plantillas** — `.env.prod.example`,
  `backend/.env.example`, `frontend/.env.example`. Todas contienen únicamente
  placeholders (`CHANGE_ME`, `TU_PASSWORD_AQUI`, `cambia-esto`).
- `.gitignore` cubre correctamente `backend/.env`, `*.env`, `.env`, `.env.*`,
  `.env.prod`, `.env.prod.*`, con negaciones `!.env.example` / `!.env.prod.example`.
- Los secretos **siguen presentes en history** y son recuperables con
  `git show <sha>:backend/.env`. El delete del working tree NO los borra de history.

**Comandos de verificación usados** (read-only, reproducibles):

```bash
git log --all --full-history -- "**/.env*" ".env*"
git show f9076f8:backend/.env   # enumeración de claves (sin reproducir valores en el doc)
git ls-files | grep -E '\.env'  # confirma que solo .example está rastreado
```

---

## 3. Premisa de seguridad

> Un secreto que estuvo en plaintext en **cualquier commit alcanzable** debe tratarse
> como **comprometido**, aunque el repo sea privado.

"Privado" reduce la superficie pero **no es un control criptográfico**. Lo exponen:
colaboradores, **forks** (ver §8.1, fork de Helptocoding / PR #1), mirror clones, tokens
de CI con acceso de lectura, y cualquier cambio de visibilidad o brecha de GitHub.

Por eso: **rotar es la mitigación primaria; reescribir history es defensa en profundidad,
no un sustituto.** Tras rotar, los valores en history quedan **inertes** (ya no abren nada).

---

## 4. Impacto real — clasificación de variables expuestas

Valores NO reproducidos. Solo se listan nombres y su naturaleza.

### `backend/.env`

| Variable | Categoría | Tipo | Estado | Motivo |
|---|---|---|---|---|
| `SECRET_KEY` | **Crítico** | Django secret | **Rotar obligatorio** | Firma sesiones, tokens de password-reset, `signing.dumps`. Reuso ⇒ forja. Inerte si no se reusa. |
| `DJANGO_SUPERUSER_PASSWORD` | **Crítico** | Credencial admin | **Rotar obligatorio** | Password del platform admin (provisiona tenants). Reuso ⇒ acceso total cross-tenant. |
| `PGPASSWORD` / `DB_PASSWORD` | **Crítico** | Credencial DB | **Rotar obligatorio** | Mismo secreto Postgres Railway bajo dos namings (`6424e48`). Alto riesgo de **reuso** en el VPS. |
| `DJANGO_SUPERUSER_USERNAME` | Bajo | Credencial admin (no secreto) | Recomendable | No es secreto, pero un username conocido facilita ataque dirigido. Cambiarlo es trivial. |
| `PGUSER` / `DB_USER` | Medio | Credencial DB (usuario) | Recomendable | Mitad del par de credenciales. No reusar el mismo usuario en el VPS (usar `vet`). |
| `SENTRY_DSN` | Medio | API token (ingesta write-only) | Recomendable (no obligatorio) | DSN público por diseño; abuso = ruido/cuota, no exfiltración. Ver §6. |
| `PGHOST`/`DB_HOST`, `PGDATABASE`/`DB_NAME`, `PGPORT`/`DB_PORT` | Bajo | Config infra Railway | No necesario | Infra Railway muerta tras migración. Sin valor contra el VPS. |
| `ALLOWED_HOSTS`, `DEBUG`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | Bajo | Config | No necesario | Flags de config/hardening, no secretos. |

### `frontend/.env`

| Variable | Categoría | Tipo | Estado | Motivo |
|---|---|---|---|---|
| `VITE_SENTRY_DSN` | Bajo | API token (público por diseño) | No necesario / opcional | Toda var `VITE_` se embebe en el bundle del cliente ⇒ ya es pública. History no amplía su superficie. |
| `VITE_API_URL` | Bajo | Public config | No necesario | URL pública de la API. No secreto. |

### Naming doble de credenciales DB

`PG*` y `DB_*` **NO son dos secretos**: son la **misma** credencial Railway bajo dos
esquemas de nombres a lo largo del history. Un solo password a rotar. Verificar que
ningún código backend siga leyendo el naming viejo (`DB_*`) con un fallback que
reintroduzca el valor.

### Lo que NO está expuesto (confirmado, y está bien)

Introducidos **después** del delete de los `.env` (era VPS) y viven solo en `.env.prod`
local git-ignored (`.env.prod.example` solo trae `CHANGE_ME`):

- `DATABASE_URL`, `REDIS_URL` / `REDIS_PASSWORD`
- B2 / rclone Application Key (vive solo en `rclone.conf`, chmod 600 — ADR p40)
- `BACKUP_ENCRYPTION_PUBLIC_KEY` (clave `age` pública, no secreta) y la privada (offline)
- SMTP / EMAIL, JWT/signing secrets más allá de `SECRET_KEY`
- **`VITE_DISCORD_WEBHOOK_URL`** — verificado: **nunca** estuvo en un `.env` real
  commiteado; solo existe como placeholder en el `.env.example` actual. No expuesto.

No requieren rotación por exposición histórica, pero deben generarse fuertes y únicos al
provisionar el VPS de todos modos.

---

## 5. Rotación obligatoria antes de prod

NO portar ninguno de estos desde Railway. Cada valor nuevo, único y generado en limpio.

### 5.1 `SECRET_KEY` (Django)

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

- Pegar en `.env.prod` (`SECRET_KEY=...`). **Nunca** reusar el valor de Railway.
- Key fresca ⇒ el valor expuesto en history queda inerte (no se puede forjar nada).
- Verificar que `settings.py` no tenga un `SECRET_KEY` de fallback hardcoded inseguro.

### 5.2 Password Postgres (VPS)

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

- Setear consistente en `.env.prod`: `PGPASSWORD`, `POSTGRES_PASSWORD`, y embebida en
  `DATABASE_URL` (el `.env.prod.example` ya advierte "keep all four credentials matching").
- Usar un **usuario distinto** al de Railway (el example ya usa `vet`, no `postgres`).
- Recordatorio del propio example: `POSTGRES_USER`/`POSTGRES_PASSWORD` solo se consumen
  en el **primer boot** del contenedor con data dir vacío. Si el volumen ya se inicializó
  con otra password, cambiar el env NO la cambia — hay que `ALTER USER vet WITH PASSWORD '...';`.

### 5.3 `DJANGO_SUPERUSER_PASSWORD` (platform admin)

- **No portar.** El `.env.prod.example` ya lo excluye deliberadamente ("NOT included on purpose").
- Bootstrap una sola vez en el VPS con `python manage.py bootstrap_superuser`, pasando
  `DJANGO_SUPERUSER_*` solo a ese proceso (procedimiento en
  [organizations, En VPS](../modules/organizations.md)), con password fresca, fuerte,
  no reusada. `createsuperuser` no sirve: crea `role='ASSISTANT'` sin organización.
- Razón: dejar credenciales en env las hace legibles desde `/proc/<pid>/environ` y rompe
  el audit trail de rotación. Cambiar también el username si era previsible (`admin`, etc.).

### 5.4 Resumen — must-rotate

| Secreto | Acción | Bloquea prod |
|---|---|---|
| `SECRET_KEY` | Generar nueva (`secrets.token_urlsafe(64)`), no reusar Railway | Sí |
| Password Postgres (`PGPASSWORD`/`POSTGRES_PASSWORD`/`DATABASE_URL`) | Nueva, única, usuario distinto | Sí |
| `DJANGO_SUPERUSER_PASSWORD` | `bootstrap_superuser` con password fresca; no portar | Sí |

---

## 6. Opcional / recomendable

| Acción | Razón |
|---|---|
| Rotar `SENTRY_DSN` / `VITE_SENTRY_DSN` | DSN = endpoint de **ingesta write-only**, público por diseño. Abuso real = inyección de eventos basura / consumo de cuota, **no** exfiltración (la PII se filtra en `beforeSend`/`scrubEvent`). Rotar (Sentry → Settings → Client Keys → nuevo, deshabilitar viejo) **solo si** hay abuso de cuota o por higiene al cambiar de hosting. Si se rota, hacerlo para ambos + rebuild del bundle. **No bloquea el deploy.** |
| Cambiar `DJANGO_SUPERUSER_USERNAME` y `PGUSER`/`DB_USER` | No son secretos, pero un par usuario+password con usuario conocido reduce la entropía del atacante. El example ya migra a `vet` — mantenerlo distinto de `postgres`/del username Railway. |
| Auditar tokens de acceso al repo de GitHub (Deploy Keys, PATs, GitHub Actions secrets, integraciones CI) | Cualquier token con acceso de **lectura** pudo clonar el history completo con los `.env`. No están en los `.env` mismos, pero son la vía por la que un secreto "privado" se filtra. Revisar/rotar los que ya no se usen post-migración. |
| Confirmar `settings.py` sin defaults inseguros | Que ningún `SECRET_KEY`/`PGPASSWORD` tenga un fallback hardcoded que también viajó en history fuera del `.env`. |

---

## 7. Hardening futuro — limpieza de history

> **La rotación (§5) es la mitigación primaria.** Tras rotar, los valores en history
> quedan inertes. La limpieza de history es **defensa en profundidad / higiene**,
> NO un sustituto de la rotación.

### Cuándo hacerlo

- **Después** del deploy estable, **no antes**. No mezclar la reescritura con el corte de producción.
- En una **ventana de bajo tráfico** de desarrollo (sin PRs abiertos ni ramas en vuelo).
- **Coordinado con todo colaborador**: tras el force-push, cada clon local existente
  queda divergido y debe **re-clonarse desde cero** (no `git pull`).
- Preferir `git filter-repo` (recomendado por el equipo de Git) sobre BFG (más simple
  pero menos mantenido).

### Riesgos (asumir explícitamente)

- **SHAs reescritos**: todo commit desde el primero que tocó `.env` cambia de hash.
  Toda referencia a un SHA viejo (docs, ADRs, mensajes, MEMORY) deja de resolver.
- **Force-push obligatorio** sobre `main` y ramas. Riesgo de borrar trabajo si alguien
  empujó entremedio.
- **Re-clone obligatorio**: cada checkout (tu máquina, CI, colaboradores) debe borrarse
  y re-clonarse. Un `pull` sobre el viejo reintroduce los objetos con secretos.
- **PRs / ramas abiertas se rompen**: las ramas no reescritas conservan los blobs con
  secretos; al mergearlas los reintroducen. Cerrarlas/recrearlas tras la limpieza.
- **GitHub cachea objetos**: aún tras force-push, GitHub puede servir commits viejos vía
  URL directa de SHA por un tiempo. Para secreto de alto valor, pedir a GitHub Support el
  purgado de caché (aquí, ya rotado, no urge).
- **Forks no se reescriben** con tu force-push (ver §8.1).

### Esbozo de procedimiento (NO ejecutar todavía)

```bash
# Tras rotar TODOS los secretos obligatorios y con backup del repo:
git filter-repo --path backend/.env --path frontend/.env --invert-paths
# Re-añadir el remoto (filter-repo lo elimina por seguridad), luego:
# git push --force --all   y   git push --force --tags
# Limpiar local: git reflog expire --expire=now --all && git gc --prune=now
```

---

## 8. Riesgos residuales y gotchas

1. **Fork de Helptocoding (PR #1) — el gotcha mayor.** Un fork en GitHub es un clon
   independiente al momento de bifurcarse. **Reescribir TU history NO toca el fork.** Si
   el fork se creó cuando `backend/.env`/`frontend/.env` aún existían en history (antes
   del delete `28eac54`, 2026-05-07), el fork **retiene los blobs con secretos**,
   accesibles vía la red de objetos compartida de GitHub. Acción: determinar cuándo se
   creó el fork y de qué rama; si retiene secretos, la única vía segura es **rotar**
   (lo que ya hacemos) + pedir a GitHub Support la eliminación del fork / purgado, o que
   el dueño lo borre. No se puede reescribir history ajeno. **Refuerza por qué la rotación,
   no el filter-repo, es la mitigación real.**

2. **Mirror clones / clones completos previos.** Cualquiera que hizo `git clone` antes del
   delete tiene los `.env` localmente para siempre. No es revocable. Refuerza: rotar.

3. **`reflog` y objetos colgantes locales.** Tras un eventual filter-repo, los blobs viejos
   sobreviven en `.git` local vía reflog hasta el `gc`. No es exposición a terceros, pero
   no asumir "limpio" sin `git reflog expire --expire=now --all && git gc --prune=now`.

4. **Forja con `SECRET_KEY` — alcance preciso.** No solo sesiones: cubre todo lo firmado
   con la key (tokens de password-reset de Django, `signing.dumps`, firmas JWT según
   config). Key fresca neutraliza todo de golpe.

5. **`VITE_*` son públicas por construcción.** Cualquier var con prefijo `VITE_` termina
   en el bundle del cliente. La pregunta no es "¿está en Git?" sino "¿tiene valor
   explotable embebida en el cliente?". `VITE_DISCORD_WEBHOOK_URL` sería la única con
   valor de abuso real (postear al canal) — **verificado que nunca estuvo en un `.env`
   real commiteado**, así que no aplica aquí.

6. **`/proc/<pid>/environ` y el patrón del platform admin.** El `.env.prod.example` ya
   excluye `DJANGO_SUPERUSER_*` por esta razón. No reintroducir esas vars en `.env.prod`
   "por comodidad" del primer boot — usar `bootstrap_superuser` con las variables solo en ese proceso.

---

## 9. Resumen ejecutivo

- **Rotación obligatoria pre-prod (3)**: `SECRET_KEY`, password Postgres
  (`PGPASSWORD`/`DB_PASSWORD`/`POSTGRES_PASSWORD`/`DATABASE_URL` = un solo secreto),
  `DJANGO_SUPERUSER_PASSWORD` (vía `bootstrap_superuser`, no portar).
- **Recomendable**: cambiar usernames (admin + Postgres); rotar DSNs de Sentry solo por
  higiene/abuso de cuota; auditar tokens/deploy keys de GitHub.
- **No necesario**: hosts/puertos/nombres de DB Railway (infra muerta), flags de config,
  `VITE_API_URL`, `VITE_SENTRY_DSN`.
- **No expuesto (confirmado)**: DATABASE_URL/REDIS/B2/age/SMTP/Discord webhook —
  introducidos post-delete, viven solo en `.env.prod` local git-ignored.
- **Driver de riesgo**: el repo privado **no es un control criptográfico**. Colaboradores,
  el fork de Helptocoding, mirror clones y tokens de CI hacen que un secreto en history
  deba considerarse comprometido. **Rotación = mitigación primaria; `filter-repo` = higiene
  posterior, no sustituto.**

---

## Apéndice — archivos revisados (sin modificar)

- `.gitignore` — cobertura `.env` adecuada (confirmada).
- `.env.prod.example` — plantilla VPS; confirma qué NO se expuso + postura del platform admin.
- `backend/.env.example` — solo placeholders.
- `frontend/.env.example` — solo placeholders (contiene `VITE_DISCORD_WEBHOOK_URL`,
  verificado nunca expuesto en history).
