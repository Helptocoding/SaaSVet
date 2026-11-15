# E01 — G07: `TurnDecision.verdict` con vocabulario cerrado

Primero lee y aplica `docs/remediaciones/orden-8/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

`TurnDecision.verdict` solo admite los cinco veredictos del árbitro (`arbiter.VERDICTS`) o vacío. Hoy el árbitro ya corre en todos los turnos y su veredicto es lo que se guarda; el texto libre del planner (`reply`, `silent`…) solo entra cuando el árbitro lanza una excepción. Esta entrega cierra el modelo y hace que ese caso deje el campo vacío en vez de inventar un veredicto. La salida del planner sigue en `facts_produced['salida']`.

No cambia nada de lo que ve el cliente ni el Inbox: el runtime nunca lee esta tabla.

## Precondición

`git log --oneline -1` muestra `chore(order8): record isolated baseline (order 8)`. En `MATRIZ.md` la fila E00 tiene resultado. Si no, `BLOQUEADA`.

## Archivos permitidos

- `backend/apps/agent/migrations/0030_turndecision_verdict_choices.py`
- `backend/apps/agent/models.py`
- `backend/apps/agent/planner.py`
- `backend/apps/agent/tests/test_b3_durable.py`
- `backend/apps/agent/tests/test_turn_decision.py`
- `docs/modules/agent.md`
- `docs/remediaciones/orden-8/MATRIZ.md` y `docs/remediaciones/orden-8/EVIDENCIA.md`

## Excepción a la regla de pruebas

En `apps/agent/tests/test_b3_durable.py` una fixture crea una fila con `verdict='reply'`, que el modelo deja de admitir. Pasa a `TurnDecision.Verdict.ANSWER`. Ninguna aserción cambia.

## Contexto

- `OrganizationalModel.save()` llama `full_clean()`, también en el `obj.save(force_insert=True)` del flush B3. Con `choices`, una fila nueva con otro valor no se guarda.
- Bajo B3 (`TurnChanges` activo), `_settle_commitment` relanza la excepción del árbitro y el turno falla, así que el flush nunca recibe un veredicto vacío ni inválido. Fuera de B3 registra `AGENT_ARBITER_FAILED` y devuelve `(None, None)`: ese es el único caso en que el campo queda vacío, y por eso lleva `blank=True`.
- `choices` y `blank` no se trasladan a la base de datos: la migración no genera SQL (`sqlmigrate` lo confirma). Las filas existentes no se reescriben; la tabla es append-only.
- `models.py` importa `arbiter`, que es un módulo puro sin imports de Django ni de modelos: no hay ciclo.
- El logger del planner es `agent.events`; la prueba nueva lo captura con `assertLogs` para que el traceback no ensucie la salida.

## Cambios

Aplícalos en este orden.

### Cambio 1 — `backend/apps/agent/models.py`

Texto actual:

```python
from .operation_model_contract import OperationManager
from .capabilities import OPERATIONS
```

Texto nuevo:

```python
from .operation_model_contract import OperationManager
from .capabilities import OPERATIONS
from . import arbiter
```

### Cambio 2 — `backend/apps/agent/models.py`

Texto actual:

```python
    Fase 1 no tiene árbitro todavía (llega en Fase 3): `verdict` guarda el
    `decision` de hoy tal cual (string libre, ~20 valores en `planner.py`);
    `because` SÍ es el enum cerrado y ortogonal desde este primer commit
    (regla de gobernanza §0.6: un presupuesto añadido después no se añade
    nunca) — se deriva con un mapeo grueso y deliberadamente conservador en
    `planner._infer_because`. Fase 3 sustituye el mapeo por el veredicto real
    del árbitro; el enum de `because` no debería necesitar romperse para eso.
    """
```

Texto nuevo:

```python
    `verdict` es el veredicto del árbitro (`Verdict`, el conjunto cerrado de
    `arbiter.VERDICTS`, ADR p55 §2). Vacío significa que el árbitro lanzó una
    excepción y no hubo veredicto; eso solo ocurre fuera del trabajo durable
    B3, que relanza el fallo. La salida operativa del planner (`reply`,
    `silent`, `escalate`…) es diagnóstico y vive en `facts_produced['salida']`
    (orden 8, G07). Las filas anteriores a É-F5 Fase 4 conservan el texto libre
    de entonces: la tabla es append-only y no se reescriben.

    `because` es el enum cerrado y ortogonal desde É-F4 Fase 1 (regla de
    gobernanza §0.6: un presupuesto añadido después no se añade nunca); se
    deriva con un mapeo grueso y deliberadamente conservador en
    `planner._infer_because`.
    """

    class Verdict(models.TextChoices):
        """Los cinco veredictos del árbitro. Un sexto exige ADR (p55 A1)."""
        CONTINUE = arbiter.CONTINUE, 'Continuar'
        DEVIATE = arbiter.DEVIATE, 'Desviar'
        SUPPLANT = arbiter.SUPPLANT, 'Suplantar'
        ABORT = arbiter.ABORT, 'Abortar'
        ANSWER = arbiter.ANSWER, 'Responder'
```

### Cambio 3 — `backend/apps/agent/models.py`

Texto actual:

```python
    verdict = models.CharField(max_length=40)
    because = models.CharField(max_length=24, choices=Because.choices)
```

Texto nuevo:

```python
    verdict = models.CharField(max_length=40, choices=Verdict.choices, blank=True)
    because = models.CharField(max_length=24, choices=Because.choices)
```

### Cambio 4 — `backend/apps/agent/migrations/0030_turndecision_verdict_choices.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
"""G07 (orden 8): `TurnDecision.verdict` admite solo los veredictos del árbitro.

Solo cambia `choices` y `blank`, que Django no traslada a la base de datos:
no genera SQL. La validación la aplica `full_clean()` al guardar filas nuevas;
las filas existentes no se reescriben porque la tabla es append-only.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0029_inbox_read_state'),
    ]

    operations = [
        migrations.AlterField(
            model_name='turndecision',
            name='verdict',
            field=models.CharField(
                blank=True,
                choices=[
                    ('continuar', 'Continuar'),
                    ('desviar', 'Desviar'),
                    ('suplantar', 'Suplantar'),
                    ('abortar', 'Abortar'),
                    ('responder', 'Responder'),
                ],
                max_length=40,
            ),
        ),
    ]
```

### Cambio 5 — `backend/apps/agent/planner.py`

Texto actual:

```python
        # declarada en el propio docstring del modelo. Ese desenlace operativo
        # no se pierde: baja a `facts_produced`, que es diagnóstico.
        produced = {'reason': result['reason']} if result.get('reason') else {}
        produced['salida'] = result.get('decision', '')
        create_local(TurnDecision,
            organization=conversation.organization,
            conversation=conversation,
            verdict=(turn_verdict.verdict if turn_verdict
                     else result.get('decision', '')),
```

Texto nuevo:

```python
        # declarada en el propio docstring del modelo. Ese desenlace operativo
        # no se pierde: baja a `facts_produced`, que es diagnóstico.
        # Sin veredicto (el árbitro lanzó una excepción) queda vacío: copiar
        # aquí la salida del planner inventaría un veredicto que nadie dio, y
        # el modelo ya no admite texto libre (orden 8, G07).
        produced = {'reason': result['reason']} if result.get('reason') else {}
        produced['salida'] = result.get('decision', '')
        create_local(TurnDecision,
            organization=conversation.organization,
            conversation=conversation,
            verdict=(turn_verdict.verdict if turn_verdict else ''),
```

### Cambio 6 — `backend/apps/agent/tests/test_b3_durable.py`

Texto actual:

```python
                         verdict='reply', because=TurnDecision.Because.PLANNER_HANDLED,
```

Texto nuevo:

```python
                         verdict=TurnDecision.Verdict.ANSWER,
                         because=TurnDecision.Because.PLANNER_HANDLED,
```

### Cambio 7 — `backend/apps/agent/tests/test_turn_decision.py`

Texto actual:

```python
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
```

Texto nuevo:

```python
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
```

### Cambio 8 — `backend/apps/agent/tests/test_turn_decision.py`

Texto actual:

```python
    def test_because_cardinality_budget(self):
        self.assertLessEqual(len(TurnDecision.Because.values), 12)
```

Texto nuevo:

```python
    def test_because_cardinality_budget(self):
        self.assertLessEqual(len(TurnDecision.Because.values), 12)


class VerdictVocabularyTests(SimpleTestCase):
    """G07 (orden 8): `verdict` solo admite los veredictos del árbitro o vacío.

    Sin DB: `choices` es una propiedad del campo y `full_clean()` la aplica al
    guardar cualquier fila nueva, también en el flush B3."""

    def test_verdict_choices_are_exactly_the_arbiter_verdicts(self):
        self.assertEqual(tuple(TurnDecision.Verdict.values), arbiter.VERDICTS)

    def test_planner_output_is_not_a_valid_verdict(self):
        field = TurnDecision._meta.get_field('verdict')
        for planner_output in ('reply', 'silent', 'escalate', 'planner_reply'):
            with self.subTest(planner_output=planner_output):
                with self.assertRaises(ValidationError):
                    field.clean(planner_output, None)

    def test_every_arbiter_verdict_and_empty_are_valid(self):
        field = TurnDecision._meta.get_field('verdict')
        for value in (*arbiter.VERDICTS, ''):
            with self.subTest(value=value):
                self.assertEqual(field.clean(value, None), value)
```

### Cambio 9 — `backend/apps/agent/tests/test_turn_decision.py`

Texto actual:

```python
class ExhaustivenessTests(TurnDecisionSetupMixin, TestCase):
```

Texto nuevo:

```python
class ArbiterFailureTests(TurnDecisionSetupMixin, TestCase):
    """G07 (orden 8): si el árbitro lanza, la fila no inventa un veredicto.

    Fuera de B3 `_settle_commitment` registra `AGENT_ARBITER_FAILED` y devuelve
    `(None, None)`. Antes la fila copiaba la salida del planner en `verdict`;
    ahora queda vacía y la salida sigue en `facts_produced['salida']`."""

    def test_arbiter_failure_leaves_an_empty_verdict(self):
        msg = self._inbound("¿eres una persona?")
        with patch('apps.agent.arbiter.decide', side_effect=RuntimeError("boom")), \
                self.assertLogs('agent.events', level='ERROR') as logs:
            planner.handle_inbound(
                self.conv, agent_settings=self.settings, triggered_by=msg,
                burst=["¿eres una persona?"],
            )
        self.assertTrue(any('AGENT_ARBITER_FAILED' in line for line in logs.output))
        row = TurnDecision.objects.get(conversation=self.conv)
        self.assertEqual(row.verdict, '')
        self.assertEqual(row.facts_produced['salida'], 'reply')
        self.assertEqual(row.active_commitment, '')


class ExhaustivenessTests(TurnDecisionSetupMixin, TestCase):
```

### Cambio 10 — `docs/modules/agent.md`

Texto actual (la fila de `TurnDecision` de la tabla de modelos, una sola línea):

````markdown
| `TurnDecision` | agent | Rastro **append-only** de cada turno (R12, É-F4 Fase 1). **El runtime NUNCA la lee** — es solo para diagnóstico/regresión. `verdict` (string libre todavía — cerrarlo a los 5 veredictos exige que el árbitro sea dueño de las 22 salidas del planner, que excede R3/R4/R7/R9), `because` (enum cerrado ORTOGONAL, ≤12 valores, `TurnDecision.Because`), `active_commitment`/`return_to`/`supplanted_by` (aún sin poblar, mismo motivo), `facts_consumed`/`facts_produced` (JSON, cero PII). `planner_used`/`tools_called`/`duration_ms` son DIAGNÓSTICO — ningún test afirma sobre ellos |
````

Texto nuevo:

````markdown
| `TurnDecision` | agent | Rastro **append-only** de cada turno (R12, É-F4 Fase 1). **El runtime NUNCA la lee** — es solo para diagnóstico/regresión. `verdict` (veredicto del árbitro, `TurnDecision.Verdict`: los cinco de `arbiter.VERDICTS`, o vacío si el árbitro lanzó una excepción fuera de B3; orden 8, G07), `because` (enum cerrado ORTOGONAL, ≤12 valores, `TurnDecision.Because`), `active_commitment`/`return_to` (los del compromiso que juzgó el árbitro) y `supplanted_by`, `facts_consumed`/`facts_produced` (JSON, cero PII; la salida del planner va en `facts_produced['salida']`). Las filas anteriores a É-F5 Fase 4 conservan el texto libre de entonces. `planner_used`/`tools_called`/`duration_ms` son DIAGNÓSTICO — ningún test afirma sobre ellos |
````

### Cambio 11 — `docs/modules/agent.md`

Texto actual:

````markdown
> **Pendiente declarado**: `TurnDecision.verdict` sigue guardando el `decision`
> de texto libre (~20 valores). Cerrarlo a los 5 veredictos exige que el
> árbitro sea dueño de las 22 salidas de turno, y eso excede lo que R3/R4/R7/R9
> necesitan. Se hará cuando el árbitro absorba el resto del `planner`.
````

Texto nuevo:

````markdown
> **Cerrado en el orden 8 (G07, 14-11-2026)**: desde É-F5 Fase 4 el árbitro
> corre en todos los turnos y `verdict` guarda su veredicto; sin compromiso en
> juego es `responder`. El modelo ahora solo admite esos cinco valores o vacío
> (`TurnDecision.Verdict`, validado por `full_clean()` al guardar). Vacío
> significa que el árbitro lanzó una excepción, lo que solo pasa fuera de B3
> (bajo B3 el turno falla). La salida del planner (`reply`, `silent`…) sigue
> en `facts_produced['salida']`, como diagnóstico.
````

## Verificación

Desde `backend/`, conservando cada salida:

```bash
R="rtk proxy python scripts/orden8_isolated.py"
for f in apps/agent/models.py apps/agent/planner.py \
  apps/agent/migrations/0030_turndecision_verdict_choices.py \
  apps/agent/tests/test_turn_decision.py apps/agent/tests/test_b3_durable.py; do
  python -m py_compile $f || echo "FAIL $f"; done; echo compilado
grep -n "result.get('decision', '')" apps/agent/planner.py
$R makemigrations --check --dry-run 2>&1 | tail -2
$R sqlmigrate agent 0030 2>&1 | tail -3
$R migrate --noinput 2>&1 | tail -3
$R test apps.agent.tests.test_turn_decision apps.agent.tests.test_contracts \
  apps.agent.tests.test_arbiter apps.agent.tests.test_b3_durable \
  --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30
```

Esperado:

- `compilado` sin ningún `FAIL`.
- El `grep` muestra una sola línea: `produced['salida'] = result.get('decision', '')`.
- `No changes detected`.
- `sqlmigrate` imprime `-- (no-op)`.
- `migrate` aplica `agent.0030_turndecision_verdict_choices`.
- **`Ran 84 tests`** y `OK`. Si aparecen decenas de `ERROR`/`FAIL` en `B3LocalIntegrationTests`, aplica la limpieza de las reglas comunes, §5, y repite antes de concluir nada.

## Cierre

- `MATRIZ.md`: G07 pasa a `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, con entrega E01, el commit y `EVIDENCIA.md §E01`. Completa la fila E01 del avance.
- `EVIDENCIA.md`: sección E01 con las salidas. Límites: las filas anteriores a É-F5 Fase 4 conservan su texto libre (append-only); la validación vive en `full_clean()`, no en un `CHECK` de base de datos, así que un `bulk_create` o un `save(validate=False)` la saltan, igual que cualquier otro campo con `choices`.

Commit: `feat(agent): restrict TurnDecision verdict to the arbiter verdicts (order 8, G07)`.
