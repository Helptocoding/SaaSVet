# Runbook — Demo Tenant + Seed (P1-8)

**Estado:** ACTIVO · **Comando:** `python manage.py seed_demo_clinic`

Crea un tenant **demo realista DENTRO del SaaS real**, como una `Organization`
normal marcada con **`is_demo=True`**. No es otra base, ni mocks, ni datos en
React: es un tenant más, aislado por multitenancy. Sirve para mostrar el producto
y para que testers exploren flujos reales sin pantallas vacías.

> Demo **privada** para testers/clientes iniciales. Sin botón "Entrar demo" ni
> credenciales públicas todavía (post-beta).

---

## 1. Qué crea

- **Organización:** «Clínica Demo SaaSlyVet», `is_demo=True`, tz America/Mexico_City, IVA 16%.
- **3 usuarios** (password `DemoSaaSlyVet2026`):
  - `demo-admin@saaslyvet.com` — ADMIN (dueño)
  - `demo-vet@saaslyvet.com` — VET
  - `demo-recepcion@saaslyvet.com` — ASSISTANT
- **Catálogo:** 8 servicios + ~18 productos con presentación y existencia inicial
  (algunos deliberadamente bajos/agotados para poblar "stock crítico").
- **~40 clientes** + **~65 mascotas** (perros/gatos/aves/exóticos, con edad/raza/sexo).
- **~75 citas**: pasadas (done/canceladas/no-show), hoy y futuras (programadas/confirmadas).
- **~50 consultas**: 45 cerradas (vacunación, gastroenteritis, control post-cirugía,
  revisión anual, urgencia) con vitales, diagnóstico, tratamiento, productos
  consumidos y algunas vacunas; + 5 abiertas (backlog clínico).
- **~60 cobros**: de consultas (mayoría pagadas, algunas confirmadas/draft) + ventas
  directas POS pagadas. Métodos mixtos efectivo/tarjeta/transferencia. Fechas
  repartidas en los últimos ~60 días para que el dashboard tenga curva.
- **Caja:** un turno abierto hoy (recepción) con los cobros del día + un movimiento
  manual de ejemplo.

### Cómo respeta las reglas de negocio

El comando **reusa los servicios autoritativos** — no escribe estado a mano:

- `provision_organization` → crea la org + admin + settings + roles RBAC + genéricos.
- `apply_stock_movement` → toda existencia/consumo de stock (bajo lock, en base units).
- `billing.services` (`confirm_invoice`, `pay_invoice`, `pay_direct_sale`,
  `get_or_create_invoice_for_medical_record`) → facturas y pagos.
- Consumo en consulta vía `MedicalRecordProduct` (descuenta stock en su `save`).

**Única escritura directa permitida:** el *backdating* de fechas
(`created_at`/anchors/`occurred_at`) para dar histórico al dashboard — mantiene la
consistencia status↔anchor que exigen los CHECK. Documentado en el comando.

---

## 2. Ejecutar (crear / actualizar)

Idempotente: re-correr **no duplica** (catálogo/personas por clave determinística;
las operaciones transaccionales solo se construyen si aún no existen).

```bash
# Local / staging
python manage.py migrate                      # aplica 0010_organization_is_demo
python manage.py seed_demo_clinic             # crea la demo
python manage.py build_daily_metrics          # puebla histórico de analytics
```

`--actor-username <user>` para elegir el superusuario que provisiona (default: el
primer `is_superuser=True`). Requiere al menos un superusuario existente.

---

## 3. Resetear la demo (datos nuevos, misma org)

Borra **solo** los datos de la org demo y la reconstruye. Conserva la org, los 3
usuarios, settings, roles y los genéricos.

```bash
python manage.py seed_demo_clinic --reset --yes
python manage.py build_daily_metrics
```

---

## 3.bis Reset automático cada 30 min (cron, ADR p49)

En producción un cron ejecuta `seed_demo_clinic --reset --yes` cada 30 min
(`10,40 * * * *`, ver [`cron-jobs.md`](./cron-jobs.md) §6.6). Endurecimientos
sobre el reset manual:

- **Atómico**: purge + rebuild en UNA transacción. Fallo a mitad → ROLLBACK total
  → demo en su último estado bueno (nunca a medio borrar).
- **Exclusión mutua**: `pg_try_advisory_xact_lock` no bloqueante — si otro reset
  corre, sale 0 sin tocar nada (no se encolan disparos).
- **Ventana de mantenimiento**: durante el reset, las ESCRITURAS de la org demo
  reciben `503 demo_resetting` (las lecturas pasan vía MVCC). Tenants reales
  jamás se ven afectados.
- **Validación inline**: conteos mínimos pre-commit; si no se alcanzan → ROLLBACK.
- **NO** encadena `build_daily_metrics` (hoy es live; el purge ya limpia los
  snapshots viejos para evitar curva fantasma).

Recuperación si el reset empieza a fallar en prod: ADR p49 §12
(`docs/decisions/2026-06-29-p49-demo-tenant-reset.md`) — deshabilitar cron,
limpiar el flag de mantenimiento, reset manual, auditorías `--org`, rehabilitar.

---

## 4. Eliminar la demo por completo

Borra la org demo entera, incluidos usuarios.

```bash
python manage.py seed_demo_clinic --delete --yes
```

---

## 5. Protecciones (no romper producción)

- **`is_demo` es la única autoridad.** `--reset`/`--delete` operan sobre la org
  con `is_demo=True`, **nunca por nombre**.
- Si hay **0** o **>1** organizations con `is_demo=True` → **aborta**.
- Las acciones destructivas exigen **`--yes`**.
- Una org real (`is_demo=False`) es intocable por el comando.

> Probar siempre en **local/staging** antes de prod. El backdating y los flujos
> de stock/cobros conviene verlos pasar las auditorías (§7) antes de tocar el VPS.

---

## 5.ter Importación de datos deshabilitada (demo)

Los 3 usuarios demo **no pueden importar datos** (operación sensible de alta
masiva). El seed reemplaza el wildcard `*.*` del rol ADMIN de la org demo por la
lista explícita de permisos **menos `import.*`** (VET/ASSISTANT ya no lo tenían).

Efecto en ambos lados (ver `apps/core/permissions.py`):
- Backend: `HybridPermission` usa los permisos de DB → `import.create` ausente → **403**.
- Frontend: `/api/me` (`build_permissions_list`) no incluye `import.*` → `can("import.create")` False → **sin CTA "Importar"**.

Scoped a la org demo (los roles son por organización) → **no afecta clínicas reales**.
Idempotente y se re-aplica en cada `seed_demo_clinic` / `--reset`. Verificado:
`import.create=False` para admin/vet/recepción; el admin conserva el resto.

## 6. Producción (VPS, docker compose)

```bash
ssh deploy@<VPS>
cd /home/deploy/apps/SaaSVet

docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend \
  python manage.py migrate

docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend \
  python manage.py seed_demo_clinic

docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend \
  python manage.py build_daily_metrics
```

Reset / delete en prod (mismo guard `is_demo`):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend \
  python manage.py seed_demo_clinic --reset --yes
```

---

## 7. Validación obligatoria (antes de darlo por hecho)

Las tres auditorías deben pasar (exit 0) sobre la base con la demo cargada:

```bash
python manage.py audit_stock_integrity
python manage.py audit_anchor_integrity
python manage.py audit_payment_ledger_integrity
```

### QA manual (los 3 roles)

Login con admin / vet / recepción (`DemoSaaSlyVet2026`) y validar:

1. Dashboard poblado (ingresos, próximas citas, pacientes recientes, stock crítico, backlog clínico).
2. Crear cliente → 3. Crear mascota → 4. Crear cita.
5. Completar consulta (vitales + diagnóstico + tratamiento) → cerrar.
6. Crear receta + dispensar.
7. Consumo de inventario en consulta descuenta stock.
8. Cobrar (confirmar + pago split).
9. Revisar historial médico de un paciente.
10. Caja: turno abierto del día con cobros.
11. Analytics con curva (tras `build_daily_metrics`).

---

## 7.bis Resultado de validación local (2026-06-21)

Primer run end-to-end contra DB local (org demo id=7):

```
owners 40 · pets 65 · services 8 · products 18 · appointments 80
medical_records 50 · invoices 65 · payments 49 · cash_sessions 1
build_daily_metrics: 5 orgs, 0 failed, snapshot demo construido
```

Auditorías (todas exit 0):

| Auditoría | Resultado |
|---|---|
| `audit_stock_integrity` | OK — sin drift |
| `audit_anchor_integrity` | OK — 4 invariantes count 0, unresolved_provenance 0 |
| `audit_payment_ledger_integrity` | OK — 0 violaciones / 129 facturas |

> **Gotcha Windows:** `audit_anchor_integrity` (modo no-json) imprime `✓` (U+2713)
> y la consola cp1252 lanza `UnicodeEncodeError` al imprimir — NO es fallo de
> datos. Correr con `PYTHONIOENCODING=utf-8` o usar `--json`. En el VPS (UTF-8)
> no ocurre.

Pendiente: QA manual de UI (login 3 roles + revisión visual, §7).

## 8. Notas / límites conocidos (post-beta)

- Sin botón "Entrar demo" / auto-login / credenciales públicas (privada por ahora).
- El seed no crea recetas (`Prescription`) — se prueban manualmente (QA #6).
- `is_demo` no se excluye aún de analytics globales (decisión post-beta).
- Reset automático cada 30 min (cron) = **implementado** (ADR p49, ver §3.bis).
