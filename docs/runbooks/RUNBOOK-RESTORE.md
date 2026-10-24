# Runbook — Disaster Recovery (RESTORE)

> **Escenario**: "El VPS desapareció." Pérdida total del host: incendio del DC,
> ransomware que cifró el disco, el proveedor canceló la cuenta, corrupción
> irreparable de Postgres, o un `rm -rf` humano. La aplicación NO existe y los
> datos locales NO existen. Solo queda la copia offsite cifrada en Backblaze B2.

Backup pipeline: [ADR p40](../decisions/2026-06-12-p40-backup-offsite-disaster-recovery.md).
Scripts: [`pg-backup.sh`](../../scripts/pg-backup.sh) · [`pg-restore.sh`](../../scripts/pg-restore.sh) · [`restore-drill.sh`](../../scripts/restore-drill.sh).

> **Paths (saaslyvet-prod-01):** el repo vive en **`/home/deploy/apps/SaaSVet`**
> (usuario `deploy`); los dumps descargados van a **`/home/deploy/restore`**. El
> host está en **America/Monterrey** (no UTC). La operación de deploy/rollback
> rutinaria está en [`../production-runbook.md`](../production-runbook.md).
>
> **Política de drill (beta):** el restore drill real es **MANUAL**, lo ejecuta el
> operador desde su máquina con la **age private key** y `--from-offsite` — es la
> prueba principal de recuperabilidad. **No** existe cron de restore (ver
> [`cron-jobs.md`](./cron-jobs.md) §5.bis).
>
> **Flujo validado en producción (2026-06-20):**
> `Backblaze B2 → descarga .dump.age → age decrypt → checksum vs manifest →
> restore a DB temporal → auditorías (anchor + payment ledger) → RESTORE VERIFIED.`

**RPO actual**: 24h (último dump nightly). **RTO objetivo**: 1–2h con este runbook.

---

## 0. Antes de empezar — qué necesitas tener a la mano

| Recurso | Dónde vive | Sin esto… |
|---|---|---|
| **age PRIVATE key** | OFFLINE: tu máquina + respaldo en papel/USB en caja fuerte. **NUNCA estuvo en el VPS.** | Los backups son ilegibles. Sin la private key NO hay recovery. |
| **rclone config / B2 App Key** | Gestor de contraseñas. La key del VPS no sirve si el VPS murió; usa una key de lectura para descargar. | No puedes bajar el backup. |
| **`.env.prod`** (o sus valores) | Gestor de contraseñas (SECRET_KEY, DB password, dominio, DSNs). | Reconstruir a mano; el backup NO incluye `.env.prod`. |
| **Repo git** | GitHub/GitLab. | Clonar de nuevo el stack. |
| **Dominio + DNS** | Registrar / Cloudflare. | Re-apuntar A record al nuevo VPS. |

> ⚠️ **Si perdiste la age PRIVATE key, detente aquí.** Los backups en B2 están
> cifrados zero-knowledge: nadie (ni tú, ni Backblaze, ni un atacante) puede
> descifrarlos sin esa clave. Custodiarla en 2 sitios offline es parte del plan.

---

## 1. Contratar un VPS nuevo

Mismo perfil que el original (ver `DEPLOY_VPS_PLAN.md`): Ubuntu 24.04, 2 vCPU,
4 GB RAM, ≥40 GB SSD. Vultr HF MX (latencia MX) o Hetzner CX22 (precio).

```bash
ssh root@<NUEVO_VPS_IP>
```

---

## 2. Hardening + Docker + herramientas

Corre el hardening estándar ([`vps-hardening.md`](./vps-hardening.md) §1–§11):
user `deploy`, SSH keys-only, UFW, Docker, log rotation, swap, UTC.

Instala las herramientas de recovery (las mismas que usa el backup):

```bash
# Docker ya quedó del hardening. Falta rclone + age:
sudo apt-get update
sudo apt-get install -y age            # o: https://github.com/FiloSottile/age/releases
curl https://rclone.org/install.sh | sudo bash
age --version && rclone version
```

---

## 3. Clonar el stack + recrear `.env.prod`

```bash
ssh deploy@<NUEVO_VPS_IP>
mkdir -p /home/deploy/apps
cd /home/deploy/apps
git clone <repo-url> SaaSVet
cd SaaSVet

cp .env.prod.example .env.prod
nano .env.prod          # rellenar TODO desde el gestor de contraseñas
chmod 600 .env.prod
```

> El backup contiene la base de datos, **no** `.env.prod`. `SECRET_KEY` puede ser
> uno nuevo (invalida sesiones JWT vivas — irrelevante en DR, nadie tiene sesión).
> La DB password en `.env.prod` debe coincidir con la que use el contenedor
> postgres en su primer arranque (igual que en el deploy original).

---

## 4. Descargar el backup desde B2

Configura rclone con una App Key (puede ser de solo lectura para recovery):

```bash
rclone config       # crear remote "saaslyvet-prod-backups" tipo B2 con keyID/appKey
# Verificar:
rclone lsf b2:saaslyvet-prod-backups/daily/ | tail
```

Baja el dump cifrado más reciente + su manifest:

```bash
mkdir -p /home/deploy/restore && cd /home/deploy/restore
LATEST=$(rclone lsf b2:saaslyvet-prod-backups/daily/ \
           --include 'vet-*.dump.age' | sort | tail -1)
echo "Recuperando: $LATEST"
rclone copy "b2:saaslyvet-prod-backups/daily/$LATEST" .
rclone copy "b2:saaslyvet-prod-backups/daily/${LATEST%.dump.age}.manifest.json" . || true
ls -la
```

> Para recuperar a una fecha más vieja (ej. ransomware silencioso que llevaba
> días corrompiendo), lista `monthly/` o elige otro `vet-*.dump.age` de `daily/`.

---

## 5. Levantar Postgres (vacío) del stack nuevo

Necesitas el contenedor `postgres` corriendo para poder restaurar dentro de él.

```bash
cd /home/deploy/apps/SaaSVet
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres
docker compose -f docker-compose.prod.yml --env-file .env.prod ps   # esperar (healthy)
```

> NO corras `release` (migrate) todavía: el dump trae el schema completo. Migrar
> primero y restaurar después choca. Restauramos a una DB **test** primero, la
> validamos, y recién entonces decidimos promover.

---

## 6. Descifrar + restaurar a una DB de verificación

Trae tu **age private key** a esta máquina temporalmente (USB; bórrala al
terminar). Restaura a una DB test (NUNCA directo sobre la futura prod):

```bash
cd /home/deploy/apps/SaaSVet
BACKUP_DECRYPTION_KEY=/ruta/segura/age.key \
  scripts/pg-restore.sh /home/deploy/restore/vet-XXXXXXX.dump.age vet_restore_test
```

`pg-restore.sh` (ADR p40):
1. descifra el `.age` a un temp 0600 (se borra al salir),
2. verifica el sha256 contra el manifest (aborta si no coincide),
3. restaura a `vet_restore_test`,
4. imprime row counts de 12 tablas críticas.

---

## 7. Verificar integridad (auditorías contables)

Corre las auditorías contra la DB restaurada — el estándar de oro:

```bash
DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/vet_restore_test" \
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  run --rm -e DATABASE_URL -e DB_CONN_MAX_AGE=0 backend \
  python manage.py audit_anchor_integrity --json        # exit 0 esperado

DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/vet_restore_test" \
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  run --rm -e DATABASE_URL -e DB_CONN_MAX_AGE=0 backend \
  python manage.py audit_payment_ledger_integrity --json # exit 0 esperado
```

Atajo: `BACKUP_DECRYPTION_KEY=/ruta/age.key scripts/restore-drill.sh /home/deploy/restore/vet-XXXX.dump.age`
hace restore + ambas auditorías + checks multi-tenant y termina en
`RESTORE VERIFIED`.

**No promuevas a producción hasta ver `exit 0` en ambas auditorías.** Si fallan,
el dump está corrupto o tampered → prueba un dump anterior.

---

## 8. Promover a la base de datos de producción

Con la verificación en verde, conviertes `vet_restore_test` en la DB real. La
forma más simple y auditable: restaurar el mismo dump sobre la DB de la app.

```bash
# Descifrar a un archivo plano temporal (se borrará).
age --decrypt --identity /ruta/age.key \
    --output /home/deploy/restore/vet.dump /home/deploy/restore/vet-XXXX.dump.age

# Recrear la DB de la app vacía y restaurar dentro.
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"

cat /home/deploy/restore/vet.dump | \
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error

# Borrar el plano temporal — contiene PII.
shred -u /home/deploy/restore/vet.dump 2>/dev/null || rm -f /home/deploy/restore/vet.dump
```

> `pg-restore.sh` se niega a tocar la DB live por diseño (guard rail). Por eso el
> paso de promoción es manual y explícito aquí — para que sea una decisión
> consciente, no un accidente.
>
> Si el dump trae una migración más nueva que el código clonado, alinéalos:
> `git checkout <commit-del-deploy>` o corre `migrate` después (Django detecta
> que ya está al día). Normalmente repo HEAD == dump.

---

## 9. Levantar la aplicación

**Gate adicional si existe Inbox/media:** antes de abrir tráfico o arrancar
workers que puedan descargar archivos, completar la
[validación de restauración de media](../compliance/cierre-b2-whatsapp-2026-10-22.md).
Mantener cerrados proxy de adjuntos, webhooks y descargas durante la intervención;
apagar solo `INBOX_MEDIA_ENABLED` no revoca por sí mismo el acceso a archivos ready.
Recuperar el registro de revocaciones/ARCO independiente del dump y reaplicarlo
con su organización y UUID; conservar timestamps originales de expiración y
retirar trabajos que pudieran descargar otra vez un objeto revocado.
Después ejecutar purga/reconciliación autorizadas, comprobar 410 para expirados/
revocados y aislamiento entre clínicas, y registrar el resultado del simulacro.
Si no se puede acreditar esa reaplicación, no reabrir el servicio de media. Las
auditorías financieras de este runbook no acreditan esta garantía. Ver también
[procedimiento ARCO](../compliance/arco.md#61-procedimiento-manual-de-cancelación-de-media).

```bash
cd /home/deploy/apps/SaaSVet
# release corre migrate (no-op si el dump ya estaba al día) + collectstatic + seed_permissions
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Re-apunta el **DNS A record** del dominio al IP del nuevo VPS (Cloudflare /
registrar). Caddy emite el cert TLS automáticamente al primer hit.

---

## 10. Verificación final (smoke)

```bash
curl -fsS https://app.tu-dominio.com/api/healthz/    # 200 ok
curl -fsS https://app.tu-dominio.com/api/readyz/     # 200 ready (DB arriba)

# Conteos vivos coinciden con lo restaurado:
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT (SELECT count(*) FROM billing_invoice)  AS invoices,
          (SELECT count(*) FROM billing_payment)  AS payments,
          (SELECT count(*) FROM medical_records_medicalrecord) AS consultas,
          (SELECT count(*) FROM organizations_organization)    AS orgs;"
```

Smoke funcional en navegador: login admin → una org → abrir un expediente y un
cobro existentes. Si los datos del último día de operación están → recovery OK.

---

## 11. Cierre — post-recovery

1. **Borra la age private key de este VPS** (solo se trajo para restaurar):
   `shred -u /ruta/age.key`. La copia offline sigue siendo la única.
2. **Rota la DB password** y el `SECRET_KEY` si sospechas que el incidente fue
   un compromiso (no solo pérdida de hardware).
3. **Re-crea la App Key de B2** que usaste para descargar (era de recovery).
4. **Re-instala los crons** ([`cron-jobs.md`](./cron-jobs.md)): el primer
   `pg-backup.sh` nuevo confirma que el pipeline volvió a funcionar.
5. **Corre `restore-drill.sh`** una vez a mano para cerrar el ciclo.
6. **Post-mortem**: ¿cuántos datos se perdieron (RPO real)? ¿cuánto tardó (RTO
   real)? Anótalo. Si el RPO de 24h dolió, es la señal para priorizar la Fase 2
   (WAL/PITR) del ADR p40.

---

## Resumen de 1 pantalla

```
VPS nuevo → hardening + docker + rclone + age
   → git clone + .env.prod (del gestor de contraseñas)
   → rclone copy del último vet-*.dump.age + manifest
   → up postgres (vacío)
   → pg-restore.sh (descifra+verifica+restaura) a vet_restore_test
   → audit_anchor_integrity + audit_payment_ledger_integrity == exit 0
   → promover a DB prod (manual, explícito) + shred del plano
   → release + up stack
   → DNS A record → nuevo IP
   → smoke healthz/readyz + conteos
   → borrar private key del VPS + rotar secretos + re-instalar crons
```


### Actualización 23-10-2026: política y herramientas de medios

La [política definida por el usuario](../decisions/2026-10-22-inbox-media-retention-policy.md)
fija 180 días y purga operativa verificada en hasta siete días tras expirar.
Usar el [procedimiento vigente de medios](../runbooks/inbox-media.md), con ledger
independiente del dump, `INBOX_MEDIA_ACCESS_HOLD=True`, workers/webhooks detenidos,
`inbox_media_ops restore-check --workers-stopped`, mantenimiento y comprobación
de inventario del proveedor antes de autorizar tráfico. El comando no reabre
tráfico. ARCO anticipado usa `inbox_media_ops revoke`: ledger duradero primero,
fencing/estado DB después; no borrar la key antes de verificar la purga.

Responsable y canal de alertas quedan pendientes operativos no bloqueantes por
decisión expresa del usuario; no registrar entrega/atención como comprobadas.
Los incidentes de purga que superan siete días sí mantienen el cierre pendiente.
