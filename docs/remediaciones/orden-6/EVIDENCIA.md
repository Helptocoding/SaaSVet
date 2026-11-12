# Evidencia del orden 6

Cada entrega añade su sección con comandos reales y resultados. No se resume lo que no se ejecutó. Lo que no se pudo comprobar se declara como límite.

## Medición previa (11-11-2026, `a7dbdaf`)

Tomada al preparar el plan, en el cluster aislado del orden 6, que se creó para ello.

| Comprobación | Resultado |
|---|---|
| `initdb` (proveedor `builtin`, `C.UTF-8`) + `init-db` + `check` | OK, sin problemas |
| `migrate --noinput` desde cero | OK en 101 s |
| Pruebas dirigidas del orden (prescriptions, bootstrap, organizations, url_audit, tenant_validation, admin_explicit_grants, ReleaseScriptTests) | 129 OK |
| Corrida amplia `apps.core apps.users apps.organizations apps.prescriptions apps.billing` | 586 OK (skipped=7), 227 s |
| Sonda temporal, `POST /api/prescriptions/<uuid>/items/` con `quantity` `0` y `-1.00` | 500 `server_error` en ambos; sigue habiendo 1 ítem. Sonda borrada. |
| Sonda temporal de supuestos (PATCH de Invoice, roles al crear organización, `emit_post_migrate_signal`, ruta legacy sin patrón, `read_only_fields = fields`) | 405; roles `ADMIN`, `AGENT`, `ASSISTANT` y `VET`; hoy `post_migrate` sí crea el superusuario; `Resolver404`; ningún campo escribible. Sonda borrada. |
| Validación en seco (12-11): E01–E05 aplicados desde los bloques de los prompts en un worktree desechable | Corrida amplia más `ReleaseScriptTests`: 602 pruebas. Todo OK salvo 7 errores de `test_phase7_hardening` por `FileNotFoundError` del sparse checkout. 33 anclas de documentos presentes una vez. El worktree se borró. |

Plantilla por entrega:

```markdown
## E0X — título (fecha, commit)

| Comando | Resultado |
|---|---|
| ... | ... |

Límites: ...
Observaciones sin cambio: ...
```

## E00 — Línea base (12-11-2026, `9da1b8b` sobre `a7dbdaf`)

Cluster: ya existía (`PG_VERSION` presente); no se creó en esta entrega. Estaba detenido y se arrancó con `pg_ctl`; `status exit=0`.

| Comando | Resultado |
|---|---|
| `git switch -c fix/orden-6-arquitectura-backend` + commit de documentos y runner | `9da1b8b` encima de `a7dbdaf` |
| `init-db` | `Base orden6_iso_20261111 lista.` |
| `check` | `System check identified no issues (0 silenced).` |
| `migrate --noinput` | `No migrations to apply.` |
| `makemigrations --check --dry-run` | `No changes detected` |
| `test apps.core apps.users apps.organizations apps.prescriptions apps.billing --keepdb --noinput` | `Ran 586 tests in 254.476s` / `OK (skipped=7)` |

Límites: ninguno.
Observaciones sin cambio: ninguna.

## E01 — B2: validación común de ítems de receta (12-11-2026)

| Comando | Resultado |
|---|---|
| `grep "requiere 'request' en su context"` en tests | sin resultados |
| `test apps.prescriptions` antes de editar | Ran 15 / OK |
| `py_compile` de `serializers.py` y `test_multitenancy.py` | OK |
| conteo de validadores / `require_same_organization` | 4 / 4 |
| `test apps.prescriptions apps.core.tests.test_tenant_validation` | Ran 31 / OK |
| `test apps.prescriptions` después | Ran 19 / OK (15 + 4: dos de API, dos estructurales) |

Efecto: `POST /api/prescriptions/<uuid>/items/` con `quantity` `0` o `-1.00` pasa de 500 (solo lo frenaba el CHECK `prescriptionitem_quantity_positive`) a 400 con `errors.quantity`.

Límites: ninguno.
Observaciones sin cambio: las pruebas existentes de `/items/` usan `rx.pk` en la URL; las nuevas usan `public_id` y funcionan.

## E02 — C2: serializers de Invoice de solo lectura (12-11-2026)

| Comando | Resultado |
|---|---|
| Precondición 1 (`InvoiceSerializer(` / `InvoiceItemSerializer(` fuera de tests) | solo las dos definiciones, el anidado `read_only=True` y tres usos en `views.py` sin `data=` |
| Precondición 2 (`invoices/<str:pk>/items`, `InvoiceItemCreateView`) | solo el comentario borrado de `InvoiceItemSerializer.validate` |
| `test apps.billing` antes | Ran 73 / OK |
| `py_compile` (serializers y cuatro archivos de prueba) | OK |
| `grep same_organization\|_get_request\|InvoiceItemCreateView` en serializers | sin resultados |
| `grep "def validate"` en serializers | 4: `validate_quantity`, `validate_name`, `validate_description`, `validate_base_price` |
| `test apps.billing` + `test_tenant_validation` + `test_url_audit` + `test_public_id_dual_exposure_audit` + `test_tenant_scoping_audit` | Ran 93 / OK |
| `test apps.billing` después | Ran 76 / OK (73 + 3: detalle de solo lectura y dos estructurales) |

Pruebas eliminadas, autorizadas: las tres filas de `InvoiceSerializer` en `FIELD_VALIDATORS`. Entradas retiradas de `ALLOWED_INT_PATTERNS` (ruta de ítems ya inexistente) y de `BASELINE` (`InvoiceItem.filter` de serializers, por el código borrado).

Límites: ninguno.
Observaciones sin cambio: la salida JSON no cambia; un campo de solo lectura se serializa igual.

## E03 — B5: comando `bootstrap_superuser` (12-11-2026)

| Comando | Resultado |
|---|---|
| Precondiciones (`_create_default_superuser` solo en `apps.py` y `test_bootstrap.py`; comando inexistente) | OK |
| `test apps.users.tests.test_bootstrap` antes | Ran 11 / OK |
| `py_compile` (`bootstrap.py`, `apps.py`, comando, `test_bootstrap.py`) | OK |
| `grep _create_default_superuser\|post_migrate.connect` fuera de tests | sin resultados |
| `test apps.users apps.organizations` | Ran 189 / OK |
| `test apps.users.tests.test_bootstrap` después | Ran 17 / OK (11 + 6) |
| `check` / `makemigrations --check --dry-run` | sin problemas / `No changes detected` |
| `bash -n scripts/pre-launch-security-check.sh` | OK |

El comando no se ejecutó contra ningún despliegue; solo pruebas en el cluster aislado.

Límites: ninguno.
Observaciones sin cambio:
- `docs/production-runbook.md` tenía una segunda mención de `createsuperuser` (línea 195, instalación desde cero con `$COMPOSE`) que el prompt no listaba. Se sustituyó por el mismo procedimiento con `bootstrap_superuser`.
- `docs/runbooks/pre-launch-security.md:98` aún dice «Login con admin SaaS (createsuperuser bootstrap)». Está fuera de los archivos permitidos y no se tocó; la comprobación final del prompt lo muestra.

## E04 — B6: `seed_permissions --prune` (12-11-2026)

| Comando | Resultado |
|---|---|
| Precondiciones (`prune` ausente en el comando y en `release.sh`) | OK |
| `test test_admin_explicit_grants test_agent_identity` antes | Ran 56 / OK |
| `py_compile` (comando y prueba nueva) | OK |
| `test test_seed_permissions_prune test_admin_explicit_grants test_agent_identity test_identity_evidence.ReleaseScriptTests` | Ran 65 / OK |

La poda no se ejecutó contra ninguna base real; solo pruebas en el cluster aislado.

Límites: ninguno.
Observaciones sin cambio: el seed sin `--prune` solo informa de los permisos fuera del catálogo; `test_admin_explicit_grants` y `test_agent_identity` siguen en 56 en conjunto.

## E05 — D2: retirada de `/api/organizations/<pk>/` (12-11-2026)

| Comando | Resultado |
|---|---|
| Precondición 1 (`organizations/${` en `frontend/src`) | sin resultados |
| Precondición 2 (`endpoint_sunset` fuera de tests) | `apps/organizations/views.py` y un comentario en `apps/appointments/views.py:47` (futuro 410 del DELETE de citas; no es código) |
| `test apps.organizations test_url_audit` antes | Ran 54 / OK |
| `py_compile` (views, urls, tres archivos de prueba) | OK |
| `grep` de restos Sunset en `views.py` / `OrganizationLegacyView` en `urls.py` | sin resultados |
| `check` | sin problemas |
| `test apps.organizations test_url_audit` después | Ran 48 / OK (54 − 7 + 1) |
| `test` anterior + `test_admin_explicit_grants` | Ran 83 / OK |
| `git grep OrganizationLegacyView\|organization-legacy -- backend docs/modules` | sin resultados |

Pruebas eliminadas, autorizadas: clase `OrganizationLegacyViewTests` (7 pruebas del 410, encabezados y log de la vista retirada). Añadida `test_legacy_pk_route_is_gone` (GET/PATCH/DELETE → 404). Las dos pruebas de `test_legacy_view_org_id_writable.py` pasan de 410 a 404 y conservan sus aserciones sobre la organización.

Límites: ninguno.
Observaciones sin cambio: `DEPRECATED_ENDPOINT_HIT` sigue vivo para `DELETE /api/appointments/<id>/` y `GET /api/inbox/conversations/`.
