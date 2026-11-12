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
