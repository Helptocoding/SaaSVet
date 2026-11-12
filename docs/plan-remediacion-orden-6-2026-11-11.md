# Orden 6 — Arquitectura backend y permisos

Fecha: **11 de noviembre de 2026**. Estado: **PLAN ACORDADO PARA IMPLEMENTACIÓN LOCAL**. Prepara el trabajo de otro agente; no acredita remediación ni despliegue.

Base: [priorización, §6](plan-remediacion-priorizado-2026-10-28.md), [inventario](pendientes-documentados-2026-10-27.md), deuda [fase 2](deuda/fase2-prioridad-alta.md), [fase 3](deuda/fase3-prioridad-media.md) y [fase 4](deuda/fase4-prioridad-baja.md), y decisiones del usuario del 11-11. Ejecución: [expediente y prompts por entrega](remediaciones/orden-6/README.md).

## 1. Decisiones vinculantes

| Tema | Decisión |
|---|---|
| Ejecutor | Claude Sonnet, un prompt autocontenido por entrega y sesión limpia. El usuario revisa entre entregas, igual que en el orden 5. |
| Alcance | Se implementan **B2, C2, B5, B6 y D2**. **A1+B4** solo se concilian en documentación: ya están hechos. **B3** se aplaza. **C1** y **C7** quedan fuera. |
| Git | Rama nueva `fix/orden-6-arquitectura-backend` desde `a7dbdaf` (`develop` tras el PR #3). Un commit por entrega, sin push, PR, merge ni despliegue. |
| Base de datos | Cluster PostgreSQL 18 propio y desechable: `%LOCALAPPDATA%/Temp/opencode/orden6_pg18_20261111`, loopback `127.0.0.1:49936`, mediante `backend/scripts/orden6_isolated.py`. Nunca la base habitual (`localhost:5432`) ni el VPS. |
| A1+B4 | Cerrados por `f325ee7` (04-11, auditoría run-1, H-3) con **funciones** en `apps/core/tenant_validation.py`, no con un mixin. El addendum de ADR p14 justifica la forma. No hay código que cambiar. |
| B2 | Una base `_PrescriptionItemBase` con los cinco validadores comunes. El anidado añade `product_name` y `product_unit`; el endpoint `/items/` añade la exigencia de `requires_prescription`. Corrige un **500** real (§3). |
| C2 | Se retira el código de escritura muerto de `InvoiceSerializer` **y de `InvoiceItemSerializer`**, que es el mismo caso: su `validate()` cita una `InvoiceItemCreateView` que ya no existe. Los dos quedan declarados de solo lectura. La regla «cliente genérico ⇒ venta directa» la retiró ADR p62: el tipo de la Invoice lo fija `Checkout.origin`. |
| B5 | Comando `bootstrap_superuser`, con la lógica en `apps/users/bootstrap.py` y sin signal `post_migrate`. Configuración ausente, incompleta o en colisión termina con código 1. **No va en `release.sh`**: el pre-launch prohíbe `DJANGO_SUPERUSER_*` en `.env.prod`, así que las variables se pasan solo al proceso del comando. Sustituye a `createsuperuser` en el runbook (§3). |
| B6 | `seed_permissions --prune` explícito. Con `--dry-run` solo lista. Nunca poda comodines (`*.*`, `recurso.*`). Nunca en `release.sh`. Registra `SEED_PERMISSIONS_PRUNED`. |
| D2 | Se borran la vista, la ruta, sus helpers de Sunset y las pruebas del 410. `/api/organizations/<pk>/` pasa a 404. |
| B3 | **Aplazado por decisión del usuario.** Queda registrada la política para cuando se retome: `User.role` se conserva como etiqueta y deja de autorizar. Sigue sirviendo para elegir el rol de sistema, identificar `ADMIN_SAAS`, al veterinario agendable y los documentos legales. Las capacidades de clínica pasan a códigos de permiso, y archivar/restaurar usa un código nuevo solo para ADMIN. El gate de 7 días de logs no es alcanzable sin producción: al retomarlo hay que acordar la evidencia sustituta. |
| C1 | Fuera: cambiar 400 por 404 exige ADR, cambio de contrato y frontend coordinado. Sigue P3 por decisión. |
| C7 | Fuera: renombrar `apps/platform` exige migrar `app_label`, `ContentType` y permisos. El workaround de etiquetas de test completas sigue vigente. |
| ADR | Ninguno nuevo. Addendums breves a p14 (el lote de `InvoiceItemSerializer` ya no se valida ahí) y a p15 (el signal pasa a comando). |
| Fuera de alcance | Frontend, migraciones de esquema, dependencias, base habitual, VPS, despliegue y cualquier limpieza no listada. |

## 2. Cobertura de los pendientes

| ID | Prioridad | Entrega | Cierre |
|---|---|---|---|
| B2 | P2 | E01 | Base compartida, diferencias explícitas, `quantity` ≤ 0 en `/items/` da 400. |
| C2 | P2 | E02 | `InvoiceSerializer` e `InvoiceItemSerializer` sin validación de escritura y de solo lectura; POST/PATCH siguen en 405. |
| B5 | P2 | E03 | Comando con códigos de salida, sin signal, documentado como vía de producción. |
| B6 | P2 | E04 | `--prune` y `--prune --dry-run` probados; comodines intactos; release sin poda. |
| D2 | P3 | E05 | Sin vista ni ruta; 404 probado; docs sin el endpoint. |
| A1 + B4 | P2 | E06 | Deuda y plan conciliados con `f325ee7`. |
| B3, C1, C7 | P2/P3 | E06 | Aplazamiento y exclusiones registrados con su motivo. |

## 3. Evidencia de partida

Medido el 11-11-2026 sobre `a7dbdaf`, working tree limpio salvo el expediente.

| Fuente | Observación | Implicación |
|---|---|---|
| `git log -- backend/apps/core/tenant_validation.py` | `f325ee7` centralizó la validación; `_validate_same_org` da 0 resultados y `NoNewAdHocTenantChecks` lo vigila. | A1+B4 solo necesitan documentación. |
| Sonda (borrada) contra `/api/prescriptions/<uuid>/items/` | `quantity` `0` y `-1.00` → **500** `server_error`. El CHECK `prescriptionitem_quantity_positive` lo frena en `full_clean`; no se guarda nada. El anidado ya daba 400. | B2 no es solo estético: el endpoint dedicado carece de `validate_quantity`. |
| `billing/views.py` | `InvoiceListCreateView` es `ListAPIView` e `InvoiceDetailView` es `RetrieveAPIView`. `test_invoice_collection_is_read_only` ya fija el 405. | Los `validate*` de ambos serializers de Invoice nunca corren. |
| `billing/serializers.py` | Al borrar esos métodos, `require_same_organization` y `same_organization` quedan sin uso; `Decimal`, `DjangoValidationError`, `timezone` y `sanitize_text` siguen en uso. | Solo se borra la línea 11. |
| `users/apps.py` | `post_migrate.connect(_create_default_superuser)`. | B5. |
| `users/models.py` | Sin manager propio: `createsuperuser` crea `role='ASSISTANT'` y `organization=None`. `platform/permissions.py` exige `role == 'ADMIN_SAAS'`. | El camino documentado de producción crea un superusuario que no puede usar `/api/platform/`. B5 lo sustituye. |
| `scripts/pre-launch-security-check.sh` | Bloqueante si `DJANGO_SUPERUSER_*` está en `.env.prod`. | El comando no puede ir en `release.sh`. |
| `seed_permissions` | Ya tiene `--dry-run` (preflight de ADR p63). Cada seed reasigna los roles de sistema al catálogo, así que un código retirado solo sobrevive como fila `Permission` y en roles propios. `*.*` no está en `PERMISSION_CODES`. | La poda debe excluir comodines o rompería una excepción documentada. |
| `organizations/views.py` | El Sunset fue el 17-08-2026; la vista responde 410 a todo. El frontend no la llama. | D2. |
| B3 | El fallback concede `PERMISSIONS[role]`, que coincide con `role_grants(role)` salvo en la demo. Once sitios de prueba borran `UserRole` a propósito. | Sustento para retomarlo; no se toca ahora. |
| Validación en seco (12-11) | Se aplicaron E01–E05 en un worktree desechable, tomando el código de los propios bloques de los prompts. La corrida amplia dio 600 pruebas, todas OK salvo 7 errores de `test_phase7_hardening` causados por el sparse checkout (sin `.github`, `docs`, `frontend`, `infra`). Las 33 anclas de texto de los documentos existen una vez. La validación detectó que E02 debía quitar una entrada del ratchet de tenant, y E02 ya lo incluye. | Los prompts producen código que compila y pasa. |
| Cluster aislado | `migrate` desde cero: 101 s. Pruebas dirigidas del orden: 129 OK. Corrida amplia `apps.core apps.users apps.organizations apps.prescriptions apps.billing`: **586 OK (skipped=7)** en 227 s. | Tiempos de referencia para los prompts. |

## 4. Trampas que los prompts cubren

- `pg_ctl start` con la salida en un pipe (`| tail`) no termina nunca: postgres hereda la salida. Se arranca con `> /dev/null 2>&1`.
- `read_only_fields = fields` dentro de `Meta` es válido porque se evalúa en el cuerpo de la clase.
- La poda no puede usar `exclude(code__in=PERMISSION_CODES)` a secas: borraría `*.*`.
- Crear una `Organization` ya crea sus roles de sistema (`_seed_roles_for_org`). Las pruebas no deben crearlos a mano.
- `test_tenant_scoping_audit` es un ratchet exacto: borrar un `InvoiceItem.objects.filter(...)` obliga a quitar su entrada del `BASELINE`, o la prueba falla por entrada obsoleta.
- Borrar un validador de producción obliga a borrar su fila en `test_tenant_validation.py`. Es la única eliminación de pruebas permitida, y solo en E02.
- `test_legacy_view_org_id_writable.py` mezcla pruebas de la ruta retirada con pruebas vigentes de `/me/`. Solo cambian las primeras.
- El backend no tiene linter en CI. Un import sin uso no rompe nada, así que se comprueba con `grep -nw`.

## 5. Entregas

| Entrega | Contenido |
|---|---|
| E00 | Rama, commit de documentos, cluster aislado, línea base |
| E01 | B2: serializers de ítems de receta |
| E02 | C2: serializers de Invoice de solo lectura |
| E03 | B5: `bootstrap_superuser` |
| E04 | B6: `seed_permissions --prune` |
| E05 | D2: retirar la vista legacy de organizaciones |
| E06 | A1+B4, B3, C1 y C7 en documentación; corrida amplia; cierre |

El orden importa poco entre E01–E05, que tocan archivos disjuntos, salvo `docs/modules/logs.md` (E03, E04 y E05). Por eso se ejecutan en serie.

## 6. Verificación y límites

- Cada entrega: pruebas dirigidas en el cluster aislado y `python -m py_compile` de los archivos Python tocados. Comandos exactos en las [reglas comunes](remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md).
- E00 y E06 ejecutan además `check`, `makemigrations --check --dry-run` y la corrida amplia (586 pruebas en la línea base, ~4 min).
- La suite global (más de 3.800 pruebas) solo se acredita en CI cuando el usuario suba la rama.
- Ninguna entrega cambia modelos: `makemigrations --check` debe seguir sin cambios.
- Sin datos reales en juego.

## 7. Estado final esperado

B2, C2, B5, B6 y D2 podrán declararse **IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE** con la evidencia de `docs/remediaciones/orden-6/EVIDENCIA.md`. A1+B4 quedan **CERRADO_PREVIAMENTE** (`f325ee7`). B3 queda **APLAZADO**; C1 y C7, **FUERA_DE_ALCANCE**. Nada de esto acredita despliegue.

## 8. Revisión entre entregas

1. El reporte trae `COMPLETA`, un hash de commit y la salida real de las pruebas.
2. `git show --stat HEAD` solo contiene archivos que el prompt autoriza.
3. Ninguna prueba se borró ni debilitó, salvo las tres filas de `InvoiceSerializer` en E02 y las pruebas del 410 en E05.
4. Ningún archivo bajo `migrations/` cambió.
