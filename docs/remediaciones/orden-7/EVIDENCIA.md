# Evidencia del orden 7

Cada entrega añade su sección con comandos reales y resultados. No se resume lo que no se ejecutó. Lo que no se pudo comprobar se declara como límite.

## Medición previa (12-11-2026, `bb5a070`)

Tomada al preparar el plan, en el cluster aislado del orden 7, que se creó para ello.

| Comprobación | Resultado |
|---|---|
| `initdb` (proveedor `builtin`, `C.UTF-8`) + `init-db` + `check` | OK, sin problemas |
| Corrida amplia inicial (`apps.core apps.users apps.organizations apps.medical_records apps.prescriptions apps.billing` + T8 de analítica) | 729 OK (skipped=7), 403 s, más unos 200 s para crear la base de pruebas |
| Validación en seco: E01–E05 aplicados en un worktree desechable | Pruebas dirigidas por entrega: E01 79, E02 226 y E03 195, todas OK. La corrida amplia de las reglas comunes dio 852 OK (skipped=7) en 456 s. `makemigrations --check`: sin cambios. |
| Validación en seco, frontend | Con `VITE_API_URL` ficticio: 79 archivos y 851 pruebas OK; `lint`, `build` y `smoke:urls` OK. |
| Fallas que la validación encontró y los prompts ya corrigen | El candado de firma rompía 44 pruebas en 9 archivos y el alta de `VET` 4 en 3, todas por fixtures sin cédula; la cédula en una variable nueva hacía fallar `test_pdf_markup_injection`; el mock de `useAuth` con un `user` inestable desmontaba el modal de Equipo. |
| Reaplicación desde los prompts | Los 96 bloques de E01–E05 se aplicaron sobre los 42 archivos de `bb5a070`, exigiendo que cada texto actual aparezca una vez y empiece y termine en límite de línea. El resultado coincide con el worktree validado en los 42 archivos. |
| Limpieza | Worktree desechable borrado. Bases del cluster borradas para que E00 parta de cero; cluster detenido y no borrado. |

Plantilla por entrega:

```markdown
## E0X — título (fecha, commit)

| Comando | Resultado |
|---|---|
| ... | ... |

Límites: ...
Observaciones sin cambio: ...
```
