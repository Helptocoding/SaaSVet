# Modulo: Backup & Disaster Recovery

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo.
> **ADR:** [`decisions/2026-06-12-p40-backup-offsite-disaster-recovery.md`](../decisions/2026-06-12-p40-backup-offsite-disaster-recovery.md).
> **Runbooks:** [`runbooks/RUNBOOK-RESTORE.md`](../runbooks/RUNBOOK-RESTORE.md) (recuperación total) · [`runbooks/cron-jobs.md`](../runbooks/cron-jobs.md) (schedule + drill).

## Qué es (y qué NO es)

Subsistema **operacional / infra**, NO una app Django. Vive como **scripts del
host** (`scripts/*.sh`) que corren en el VPS como user `deploy` (vía cron), no
dentro de ningún contenedor. Cierra el riesgo **P0: pérdida total de datos si
muere el VPS** (incendio del DC, ransomware, corrupción de Postgres, error
humano).

No tiene modelos, vistas ni serializers. No emite eventos JSON a stdout (sus
logs van a `/var/log/vet-*.log` en el host). Lee la DB **fuera de banda** vía
`pg_dump` y nunca importa código de dominio.

Capa 4 de `DEPLOY_VPS_PLAN.md`, endurecida por ADR p40 (FASE 1, pre-beta).

## Componentes

| Script | Rol | Dónde corre |
|---|---|---|
| `scripts/pg-backup.sh` | Backup nightly: dump → validar → cifrar → subir offsite | cron 03:00 UTC (host) |
| `scripts/pg-restore.sh` | Restaurar un dump (`.dump` o `.dump.age`) a una **DB test** | manual / invocado por el drill |
| `scripts/restore-drill.sh` | Drill: restaura + corre auditorías → `RESTORE VERIFIED` | cron mensual (host) + manual |
| `scripts/disk-alert.sh` | Alerta de disco (incluye `/var/backups/vet`) | cron horario (host) |
| `scripts/crontab.example` | Plantilla de cron del VPS | install una vez |

## Pipeline de backup (`pg-backup.sh`)

```
pg_dump -Fc → pg_restore --list (validar) → sha256 + manifest
            → age encrypt (PUBLIC key)      → rclone copy a B2 (daily/ + monthly/)
            → retención local 14d           → deadman ping (SOLO en éxito)
```

- **Validación antes de confiar**: el dump se re-lee con `pg_restore --list`
  dentro del contenedor postgres. Cero TOC entries → exit 4, dump borrado.
- **Manifest JSON** por backup: fecha UTC, DB, versión Postgres, formato, TOC
  entries, tamaño + sha256 (plano y cifrado), age recipient. Viaja junto al
  backup → el restore verifica el checksum.
- **Cifrado client-side asimétrico (age)**: solo la copia `.age` sale del host.
  La **public key** cifra; la **private key vive OFFLINE**, nunca en el VPS →
  un host comprometido no descifra el histórico (zero-knowledge).
- El `.dump` plano se queda **solo local** (mismo trust-zone que la DB live).

### Variables (env / cron / `.env.prod`)

| Var | Default | Rol |
|---|---|---|
| `RCLONE_REMOTE` | `""` | `remote:bucket[/path]` offsite. **Prod: obligatorio** (vacío → exit 6) |
| `BACKUP_ENCRYPTION_PUBLIC_KEY` | `""` | age recipient (`age1...`) o path a recipients file. NO es secreto |
| `HEALTHCHECK_URL` | `""` | deadman ping (Healthchecks.io) |
| `BACKUP_DIR` | `/var/backups/vet` | dir local de dumps |
| `RETENTION_DAYS` | `14` | retención **local** (offsite la maneja B2 lifecycle) |
| `BACKUP_DECRYPTION_KEY` | `""` | (restore/drill) age **private key**, máquina del operador, **NUNCA en el VPS** |

### Exit codes

- `pg-backup.sh`: `0` OK · `1` precondición · `2` dump pequeño/vacío · `3` pg_dump
  falló · `4` validación `pg_restore --list` falló · `5` cifrado/rclone no
  disponible · `6` offsite mal configurado o falló (prod).
- `restore-drill.sh`: `0` RESTORE VERIFIED · `1` precondición · `2` restore falló
  · `3` health check falló.
- `pg-restore.sh`: `0` OK · `1` precondición / decrypt / checksum mismatch.

## Reglas (no negociables)

- **Fail-loud en producción** (`ENVIRONMENT=production`): sin `RCLONE_REMOTE` el
  backup se niega a correr (exit 6). Un backup que vive solo en el VPS que
  protege NO es backup.
- **Nunca subir plano offsite**: si va offsite, va cifrado. Falta `age`/pubkey
  con `RCLONE_REMOTE` set → exit 5.
- **Offsite inmutable**: bucket B2 con **Object Lock** + lifecycle. La App Key
  del VPS tiene `list/read/write` y **NO** `deleteFiles`/`bypassGovernance` →
  ransomware con la key del host no puede borrar el histórico. La expiración la
  gobierna B2, el script nunca borra offsite.
- **Restore siempre a DB test**: `pg-restore.sh` rechaza la DB live (guard-rail).
  Promover a producción es un paso manual explícito (RUNBOOK-RESTORE §8).
- **Anchors/append-only intactos tras restore**: el dump `-Fc` es snapshot
  consistente; las auditorías del drill lo verifican (abajo).

## Retención

| Tier | Frecuencia | Retención | Owner de expiry |
|---|---|---|---|
| local | nightly | 14 días | `pg-backup.sh` (`find -mtime`) |
| `daily/` offsite | nightly | 30 días | B2 lifecycle |
| `monthly/` offsite | día 01 | 12 meses | B2 lifecycle |

## Restore drill — dos niveles

| Nivel | Prueba | Cómo | Cuándo |
|---|---|---|---|
| **Local (auto)** | dump local → restore → auditorías | cron `restore-drill.sh` (usa `.dump` plano, sin private key) | día 1 de mes, desatendido |
| **Offsite (MANUAL)** | B2 → download → **decrypt** → restore → auditorías | `restore-drill.sh --from-offsite` con la private key | **mensual, a mano** |

> ⚠️ El cron NO prueba la cadena de desastre real (download + decrypt desde B2).
> Si la private key se perdió/corrompió o el `.age` subió mal, solo te enteras el
> día del desastre. La prueba offsite manual mensual es **obligatoria**
> (cron-jobs.md §5.bis).

## Validación post-restore (tablas críticas + health checks)

El drill corre, contra la DB **restaurada**, los mismos audits que el cron live:

- `audit_anchor_integrity --json` → anchors (`paid_at`/`confirmed_at`/
  `cancelled_at`/`closed_at`) íntegros (exit 0).
- `audit_payment_ledger_integrity --json` → `Invoice.status` cuadra con el ledger
  (`paid ⟺ remaining_balance==0`) (exit 0).
- Multi-tenant: `organization_id IS NULL` count = 0 en `billing_invoice`,
  `patients_pet`, `medical_records_medicalrecord`.
- Signo financiero: `amount <= 0` count = 0 en `billing_payment`,
  `billing_refundpayment`.

Un restore solo cuenta como válido si **todos** pasan → "restauré filas" se
convierte en "restauré un estado contable y multi-tenant válido".

**Datos críticos cubiertos** (irreemplazables): ledger financiero append-only
(`Payment`/`RefundPayment`/`CreditNote`), historiales clínicos
(`MedicalRecord`/`VitalSigns`/`Prescription`/`VaccineRecord` — conservación
NOM-024/046), pacientes, inventario (`StockMovement`), auditorías. Analytics
snapshots (`DailyOrgMetrics`) son reconstruibles de anchors → menor prioridad.

## RPO / RTO

- **RPO actual: 24h** — máximo se pierde el día desde el último dump (03:00 UTC =
  21:00 MX, clínica cerrada). Aceptado pre-beta.
- **RTO esperado: 1–2h** — siguiendo RUNBOOK-RESTORE.md (VPS nuevo → restore →
  verificar → promover → DNS).
- FASE 2 (WAL/PITR, DD-011 (`docs/deferred-decisions.md`)) baja RPO a minutos.

## Manejo de claves

| Clave | Dónde | Si se filtra |
|---|---|---|
| age **public** | repo / `.env.prod` (no secreto) | irrelevante (solo cifra) |
| age **private** | OFFLINE: operador + respaldo papel/USB. Nunca en el VPS | rotar keypair + re-cifrar; el drill offsite ejerce el descifrado |
| B2 App Key (VPS) | `~/.config/rclone/rclone.conf` (chmod 600), scoped sin delete/bypass | revocar + recrear; Object Lock protege el histórico igual |

La **custodia de la private key es el nuevo single-point-of-failure** → copia
dual offline + prueba de descifrado en cada drill offsite.

## Estado

- **FASE 1 (pre-beta)**: implementada (ADR p40). Backup cifrado offsite +
  inmutable + restore probado + drill + runbook.
- **FASE 2 (hardening)**: WAL archiving / PITR — diferida, DD-011 (`docs/deferred-decisions.md`).
- **FASE 3 (escala)**: geo-redundancia / DB managed — diferida, DD-012 (`docs/deferred-decisions.md`).

Prohibido en FASE 1 (overengineering pre-beta): pgBackRest, WAL, PITR, DB
managed, cambios a la arquitectura Docker.
