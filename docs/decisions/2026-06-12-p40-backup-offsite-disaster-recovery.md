# ADR p40: Backup Offsite & Disaster Recovery (FASE 1 pre-beta)

**Fecha**: 2026-06-12
**Estado**: Aceptado — implementado (FASE 1; FASE 2/3 diferidas)
**Documentos relacionados**:
- `DEPLOY_VPS_PLAN.md` Capa 4 (Postgres data layer + backups) — esto la extiende
- `docs/runbooks/RUNBOOK-RESTORE.md` (procedimiento de recuperación total)
- `docs/runbooks/cron-jobs.md` (schedule + exit codes)
- Scripts: `scripts/pg-backup.sh`, `scripts/pg-restore.sh`, `scripts/restore-drill.sh`
- Invariantes en `docs/system-reference.md` §3 (append-only, anchors, multitenancy)

## Contexto

Beta cerrada inminente con datos **irreemplazables** sobre un **VPS único** (aún
no contratado): ledger financiero append-only (`Payment`/`RefundPayment`/
`CreditNote`), historiales clínicos con obligación legal de conservación
(NOM-024/NOM-046, ~5 años), pacientes, inventario y auditorías. Todo
multi-tenant.

El backup que existía (Capa 4) hacía `pg_dump -Fc` nightly con retención local
14 días y un upload offsite **opcional y apagado** (`RCLONE_REMOTE` vacío por
default), sin cifrado, sin inmutabilidad y sin restore probado. Consecuencia: los
backups vivían en el **mismo VPS** que protegen. Riesgo **P0 = pérdida total del
negocio** ante: muerte del VPS, ransomware, corrupción de Postgres o error
humano. Un comprador haciendo due diligence lo marcaría como bloqueante.

Restricción explícita de esta fase: **NO** pgBackRest, **NO** WAL archiving, **NO**
PITR, **NO** DB managed, **NO** cambios a la arquitectura Docker. Debe poder
probarse localmente sin VPS. Confiabilidad > complejidad.

## Decisión

Activar un pipeline offsite **3-2-1-1-0** (3 copias, 2 medios, 1 offsite, 1
inmutable, 0 errores de restore) sobre Backblaze B2, **extendiendo** los scripts
existentes — sin reescribir la arquitectura.

### 1. Pipeline de backup (`pg-backup.sh`)

```
pg_dump -Fc → pg_restore --list (validar) → sha256 + manifest
            → age encrypt (PUBLIC key)     → rclone copy a B2 (daily/ + monthly/)
            → retención local 14d          → deadman ping (solo en éxito)
```

- **Validación antes de confiar**: el dump se re-lee con `pg_restore --list`
  dentro del contenedor (sin cliente pg en el host). Cero TOC entries → exit 4,
  se borra el dump corrupto.
- **Manifest JSON** por backup: fecha UTC, DB, versión Postgres, formato,
  TOC entries, tamaño + sha256 del plano y del cifrado, recipient age. El
  manifest viaja junto al backup → el restore verifica checksum.
- **Cifrado client-side asimétrico (age)**: solo la copia cifrada sale del host.
  La **public key** (`age1wkp…q6a8`) cifra; la **private key vive OFFLINE**,
  nunca en el VPS. Un host comprometido **no puede descifrar** el histórico
  (zero-knowledge real).

### 2. Inmutabilidad (Backblaze B2)

- Bucket `saaslyvet-prod-backups`: **Object Lock ENABLED** + SSE-B2 +
  **lifecycle rules** que expiran `daily/` a 30d y `monthly/` a 12 meses.
- La **App Key del VPS** debe tener `listBuckets, listFiles, readFiles,
  writeFiles` y **NO** `deleteFiles` ni `bypassGovernance`. Ransomware con la key
  del host **no puede borrar ni sobrescribir** objetos locked. La expiración la
  gobierna B2, no el script (el script nunca borra offsite).

### 3. Local-only en desarrollo, fail-loud en producción

```
ENVIRONMENT=production + RCLONE_REMOTE vacío   → exit 6 (no backup sin offsite)
ENVIRONMENT=production + offsite falló         → exit 6 + deadman NO pingea → alerta
RCLONE_REMOTE set + falta age/pubkey           → exit 5 (jamás subir plano)
dev (ENVIRONMENT != production), sin remote     → modo local solamente (warn)
```

### 4. Restore cifrado (`pg-restore.sh`)

Acepta `.dump` y `.dump.age`. Para `.age`: descifra con `BACKUP_DECRYPTION_KEY`
(private key, máquina del operador) a un temp `0600` que se borra al salir,
verifica sha256 contra el manifest, y restaura **siempre a una DB test** (guard
rail rechaza la DB live). La promoción a producción es un paso manual explícito
documentado en el runbook.

### 5. Restore drill (`restore-drill.sh`, mensual)

Prueba que el backup es **recuperable** end-to-end: restaura el último dump a una
DB descartable y corre `audit_anchor_integrity` + `audit_payment_ledger_integrity`
+ checks multi-tenant (org_id no nulo, `amount > 0`). Termina en `RESTORE
VERIFIED`. En cron usa el **`.dump` plano local** (sin private key, desatendido);
el path cifrado/offsite se verifica a mano desde la máquina del operador con
`--from-offsite`. El audit contra la DB restaurada se hace pasando `DATABASE_URL`
como env de proceso (no en argv) para no exponer la password.

### 6. Retención (pre-beta, sin PITR)

| Tier | Frecuencia | Retención | Owner de expiry |
|---|---|---|---|
| local | nightly | 14 días | `pg-backup.sh` (find -mtime) |
| `daily/` offsite | nightly | 30 días | B2 lifecycle |
| `monthly/` offsite | día 1 | 12 meses | B2 lifecycle |

## Alternativas evaluadas

- **`rclone crypt` (cifrado simétrico)**: rechazado. La clave vive en
  `rclone.conf` en el host → un VPS comprometido lee todo el histórico. El
  esquema asimétrico de age da zero-knowledge ante host owned.
- **Solo SSE-B2 (cifrado server-side de Backblaze)**: insuficiente como única
  capa. Protege el dato en reposo en B2, pero no es zero-knowledge (B2 tiene las
  llaves) y no protege contra una App Key del host con permiso de borrado. Se usa
  **además** del cifrado client-side, no en su lugar.
- **Cloudflare R2**: rechazado para esta fase. Object Lock menos maduro vía
  rclone; la inmutabilidad es el requisito #1 anti-ransomware.
- **pgBackRest / WAL archiving / PITR**: diferido a FASE 2. Baja el RPO a minutos
  pero introduce `archive_command` (cambio de schema operativo, riesgo de
  disco-lleno) — fuera de scope pre-beta.
- **DB managed (Neon/Supabase/RDS)**: diferido a FASE 3. Backups gestionados y
  PITR nativo, pero costo/complejidad injustificados en beta; el trigger es
  Postgres >70% CPU sostenido.
- **Mantener offsite apagado hasta tener VPS**: rechazado. El riesgo P0 se cierra
  con config + scripts ahora; dejarlo para "después del deploy" es exactamente
  como se pierden los primeros datos reales.

## RPO / RTO

- **RPO actual: 24h** — se pierde como máximo el día desde el último dump nightly
  (03:00 UTC = 21:00 MX, clínica cerrada). Aceptable para beta; el ledger
  financiero append-only del día se reconstruye de tickets físicos si hace falta.
- **RTO esperado: 1–2h** — siguiendo `RUNBOOK-RESTORE.md` (VPS nuevo → hardening
  → clone → descargar → descifrar → restaurar → verificar → promover → DNS).
- **Objetivo FASE 2**: RPO 5–15min (PITR vía WAL), RTO ~1h.

## Manejo de claves

| Clave | Dónde | Quién la tiene | Si se filtra |
|---|---|---|---|
| age **public** | repo / `.env.prod` (no secreto) | cualquiera | irrelevante (solo cifra) |
| age **private** | OFFLINE: máquina operador + respaldo papel/USB en caja fuerte. **Nunca en el VPS.** | solo el operador | comprometido = el atacante puede descifrar backups que también haya robado → rotar keypair + re-cifrar |
| B2 App Key (VPS) | `~/.config/rclone/rclone.conf` (chmod 600). Scoped: sin delete, sin bypass. | el VPS | revocar en consola B2 + re-crear; Object Lock protege el histórico igual |
| DB password / `SECRET_KEY` | gestor de contraseñas; en `.env.prod` (chmod 600, git-ignored) | operador | rotar |

**Custodia de la private key es el nuevo single-point-of-failure** y se mitiga
con copia dual offline + prueba de descifrado en cada restore drill.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Pérdida de la age private key → backups ilegibles | 2 copias offline; el drill `--from-offsite` ejerce el descifrado periódicamente |
| App Key del VPS con `deleteFiles`/`bypassGovernance` | Prohibido por ADR; la key del VPS es write/list/read sin delete → Object Lock efectivo |
| Plano local 14d contiene PII | Mismo trust zone que la DB live en el mismo host; solo el cifrado sale offsite |
| Offsite falla silenciosamente | Producción: exit 6 + deadman suprimido → Healthchecks.io alerta |
| Object Lock en compliance mode bloquea limpieza | Usar **governance** mode en B2 (override administrativo posible) hasta madurar |
| Backup corrupto sube sin que nadie note | `pg_restore --list` (exit 4) + sha256 en manifest + drill mensual |

## Consecuencias

- ✅ Sobrevive pérdida total del VPS, ransomware, corrupción y error humano.
- ✅ Due-diligence-ready: backups cifrados, inmutables y con restore probado.
- ✅ Costo ~<$1/mes en beta (B2 $6/TB; Object Lock + cifrado gratis).
- ✅ Cero cambios a Docker/DB; probable localmente; portable al VPS tal cual.
- ⚠️ RPO 24h (no continuo) — explícitamente aceptado pre-beta; FASE 2 lo baja.
- ⚠️ Nueva responsabilidad operativa: custodia de la private key age.

## Criterio de terminado (FASE 1)

1. ✅ Backup manual corre local y genera dump válido (`pg_restore --list` OK).
2. ✅ Lo cifra con age (public key) y produce `.dump.age` + manifest.
3. ✅ Lo sube por rclone a B2 (`daily/`, y `monthly/` el día 01).
4. ✅ Se restaura en una DB test desde el `.age` (descifrado + checksum).
5. ✅ `audit_anchor_integrity` + `audit_payment_ledger_integrity` pasan (exit 0).
6. ✅ Documentado: este ADR + `RUNBOOK-RESTORE.md` + `cron-jobs.md`.

## FASE 2 / FASE 3 (diferidas, NO en este ADR)

Registradas en `docs/deferred-decisions.md` con su trigger de activación:

- **FASE 2 (hardening) — [DD-011]**: WAL archiving (pgBackRest/wal-g) → PITR;
  drill mensual ya está. RPO → minutos.
- **FASE 3 (escala) — [DD-012]**: geo-redundancia (2º bucket/región) o DB managed
  con PITR nativo cuando Postgres >70% CPU o >10 clínicas.
