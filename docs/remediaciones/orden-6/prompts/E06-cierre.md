# E06 — Cierre: documentación de deuda, corrida amplia y expediente

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Registrar en la deuda el estado de los nueve IDs del orden, comprobar el conjunto con la corrida amplia y cerrar el expediente. No se toca código.

## Precondición

`git log --oneline a7dbdaf..HEAD` muestra siete commits: los dos de E00 y uno por cada entrega E01–E05. En `MATRIZ.md`, B2, C2, B5, B6 y D2 están en `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Si no, `BLOQUEADA`.

## Archivos permitidos

- `docs/deuda/fase2-prioridad-alta.md`, `docs/deuda/fase3-prioridad-media.md`, `docs/deuda/fase4-prioridad-baja.md`
- `docs/modules/organizations.md` (solo la línea indicada)
- `docs/runbooks/pre-launch-security.md` (solo la línea indicada)
- Expediente del orden 6 (`README.md`, `MATRIZ.md`, `EVIDENCIA.md`)
- Este prompt, `docs/remediaciones/orden-6/prompts/E06-cierre.md`: se ajustó tras revisar E03. Aparecerá como modificado en `git status`; inclúyelo en el commit **sin editarlo**.

## Paso 1. Líneas de estado en la deuda

Al final de cada sección indicada añade una línea en blanco y la línea de estado, justo antes del `---` que cierra la sección. Es el mismo formato que usó el orden 5 en C3–C6. El enlace es relativo a `docs/deuda/`.

**`docs/deuda/fase2-prioridad-alta.md`**

- Sección que empieza por `## A1 —`:

  ```markdown
  **Estado:** cerrado previamente por `f325ee7` (04-11-2026, auditoría run-1, H-3) con funciones en `apps/core/tenant_validation.py` en lugar del mixin; el motivo está en el addendum de [ADR p14](../decisions/2026-05-16-p14-tenant-validators-day3.md). Conciliado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)).
  ```

- Sección que empieza por `## D2 —`:

  ```markdown
  **Estado:** cerrado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)). Sin producción no había métrica de uso que acreditar, y el frontend no llamaba al endpoint. La vista se borró y la ruta responde 404.
  ```

**`docs/deuda/fase3-prioridad-media.md`**

- Sección que empieza por `## B2 —`:

  ```markdown
  **Estado:** cerrado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)). La base común es `_PrescriptionItemBase`, sin mixin: la validación de organización la aporta `require_same_organization`. Corrigió un 500 de `/items/` con cantidad no positiva.
  ```

- Sección que empieza por `## B3 —`:

  ```markdown
  **Estado:** aplazado en el orden 6 por decisión del usuario (11-11-2026). El gate de siete días de logs de producción no es alcanzable sin producción. Política acordada para cuando se retome: `User.role` se conserva como etiqueta (qué rol de sistema se asigna, `ADMIN_SAAS`, veterinario agendable, documentos legales) y deja de autorizar; las capacidades de clínica pasan a códigos de permiso, y archivar/restaurar usa un código nuevo solo para ADMIN. Sustituye el paso 3 de este ítem (`User.role` nullable). Ver el [plan del orden 6](../plan-remediacion-orden-6-2026-11-11.md), §1.
  ```

- Sección que empieza por `## B4 —`:

  ```markdown
  **Estado:** cerrado previamente por `f325ee7` junto con A1: `_validate_same_org` ya no existe y `NoNewAdHocTenantChecks` impide reintroducirlo. Conciliado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)).
  ```

- Sección que empieza por `## B5 —`:

  ```markdown
  **Estado:** cerrado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)). El comando no va en `release.sh`, porque el pre-launch prohíbe `DJANGO_SUPERUSER_*` en `.env.prod`: las variables se pasan solo a su proceso. Sustituye a `createsuperuser` en los runbooks, que creaba `role='ASSISTANT'` sin organización.
  ```

- Sección que empieza por `## B6 —`:

  ```markdown
  **Estado:** cerrado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)). `--dry-run` ya existía por ADR p63. `--prune` nunca borra comodines y nunca corre en `release.sh`. Al borrar un `Permission` solo desaparecen sus concesiones en roles: no borra `UserRole`.
  ```

**`docs/deuda/fase4-prioridad-baja.md`**

- Sección que empieza por `## C1 —`:

  ```markdown
  **Estado:** fuera del alcance del orden 6 por decisión del usuario: exige ADR, cambio de contrato y frontend coordinado. Sigue P3.
  ```

- Sección que empieza por `## C2 —`:

  ```markdown
  **Estado:** cerrado en el orden 6 ([expediente](../remediaciones/orden-6/README.md)). ADR p62 dejó la regla sin uso: las Invoice nacen al postear un Checkout y su tipo lo fija `Checkout.origin`. En lugar de moverla a un servicio, se retiró el código de escritura muerto de `InvoiceSerializer` e `InvoiceItemSerializer`.
  ```

- Sección que empieza por `## C7 —`:

  ```markdown
  **Estado:** fuera del alcance del orden 6 por decisión del usuario. El workaround de etiquetas de prueba completas sigue vigente.
  ```

Comprueba: `grep -c "orden 6" docs/deuda/fase2-prioridad-alta.md docs/deuda/fase3-prioridad-media.md docs/deuda/fase4-prioridad-baja.md` debe dar `2`, `5` y `3`.

## Paso 2. `docs/modules/organizations.md`

Sustituye la línea

```markdown
Gate para corte del fallback: `RBAC_FALLBACK_ALLOWED` ausente en logs por 7 dias consecutivos → se puede eliminar el campo `User.role`.
```

por

```markdown
Corte del fallback (deuda B3): **aplazado** en el orden 6. El gate de 7 dias de logs no es alcanzable sin produccion. Cuando se retome, `User.role` se conserva como etiqueta y deja de autorizar (ver [plan del orden 6](../plan-remediacion-orden-6-2026-11-11.md), §1).
```

## Paso 2b. `docs/runbooks/pre-launch-security.md`

Pendiente que dejó E03: la prueba E2E manual aún nombra `createsuperuser`. Dentro del bloque de §2.4, sustituye la línea

```text
2. Login con admin SaaS (createsuperuser bootstrap)
```

por

```text
2. Login con admin SaaS (creado con manage.py bootstrap_superuser)
```

Después, desde la raíz, `git grep -n "createsuperuser" -- docs/production-runbook.md docs/runbooks docs/security docs/modules .env.prod.example scripts/pre-launch-security-check.sh` solo puede mostrar líneas que digan que **no** se use (`No usar`, `no sirve`, `Do not use`).

## Paso 3. Verificación final

Desde `backend/`, conservando cada salida:

```bash
R="rtk proxy python scripts/orden6_isolated.py"
$R check 2>&1 | tail -2
$R makemigrations --check --dry-run 2>&1 | tail -2
$R test apps.core apps.users apps.organizations apps.prescriptions apps.billing --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30
$R test apps.agent.tests.test_identity_evidence.ReleaseScriptTests --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Esperado: `No changes detected`, y la corrida amplia con **`Ran 600`** y `OK (skipped=7)`: las 586 de la línea base, más 4 de E01, 3 de E02, 6 de E03 y 7 de E04, menos 6 de E05. Si el número difiere pero todo pasa, explica la diferencia en evidencia. Si algo falla, `BLOQUEADA`.

Desde la raíz:

```bash
git diff a7dbdaf --stat -- '*/migrations/*' frontend scripts/release.sh
```

No debe imprimir nada.

Al terminar, detén el cluster sin borrarlo:

```bash
"/c/Program Files/PostgreSQL/18/bin/pg_ctl.exe" -D "$HOME/AppData/Local/Temp/opencode/orden6_pg18_20261111" -m fast -w stop > /dev/null 2>&1; echo "stop exit=$?"
```

## Paso 4. Expediente

- `MATRIZ.md`: A1 + B4 en `CERRADO_PREVIAMENTE` (commit `f325ee7`, evidencia `EVIDENCIA.md §E06`); B3 en `APLAZADO`; C1 y C7 en `FUERA_DE_ALCANCE`, todos con entrega E06. Completa la fila E06 del avance.
- `EVIDENCIA.md`: sección E06 con la salida de los comandos del paso 3 y estos límites:
  - La suite global (más de 3.800 pruebas) solo queda probada en CI cuando el usuario suba la rama.
  - Sin despliegue. `bootstrap_superuser` y `--prune` no se ejecutaron contra ninguna base real.
  - El cluster aislado quedó detenido y no se borró.
- `README.md`: cambia el estado a `implementado localmente, pendiente de revisión y subida por el usuario`.

## Cierre

Commit con los tres archivos de deuda, `docs/modules/organizations.md`, `docs/runbooks/pre-launch-security.md`, el expediente y este prompt: `docs(order6): record debt status and close order 6`.

En «Para revisar»: subir la rama y confirmar CI, y leer el procedimiento de `bootstrap_superuser` antes del próximo despliegue.
