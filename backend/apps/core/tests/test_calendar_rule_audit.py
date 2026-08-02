"""
Guardia de la regla de calendario: "hoy" es el día local de la ORGANIZACIÓN.

Contexto (hallazgo 2026-08-01, encontrado al corregir un test que fallaba a
medianoche). Cinco sitios de código de negocio evaluaban reglas de calendario
con `datetime.date.today()`, que devuelve la fecha del **sistema operativo**:
ni la de Django (`settings.TIME_ZONE`) ni la de la clínica. Medido en la
máquina de desarrollo mientras se diagnosticaba:

    settings.TIME_ZONE   : UTC
    UTC ahora            : 2026-08-02 00:55
    date.today()         : 2026-08-01   <- el validador
    timezone.localdate() : 2026-08-02   <- todo lo demás

Efecto en producción, que es lo que importa: con servidor en UTC y clínica en
México (UTC−6), `date.today()` va **un día por delante** del día local de la
clínica durante seis horas cada noche. El validador de vacunas aceptaba
registrar una aplicación con fecha de *mañana* en un expediente clínico.

La regla NO es "la fecha de una vacuna no puede ser futura" (eso es un caso).
La regla es:

    Toda validación o filtro basado en "hoy" se evalúa contra el día local de
    la organización — `apps.core.datetime_utils.org_today_local(org)`, o
    `serializer_today(self)` dentro de un validador de serializer.

Por qué en código y no solo en la documentación: el proyecto ya aprendió esto
(ADR p54 §2, "una regla en el prompt es advisoria; una regla en código es
vinculante"). Estos cinco sitios convivían con `org_today_local` ya existente
y usado por `agent` y `analytics` — nadie los mezcló a propósito, simplemente
nada lo impedía.

Detección por AST, no por texto: cuatro de las ocurrencias que un `grep`
encuentra hoy están dentro de comentarios que EXPLICAN la regla.

Tolerancia CERO, sin baseline: tras la corrección no queda ninguna ocurrencia,
y un gate en cero es más fuerte que un ratchet. Si aparece una legítima, la
discusión es explícita — se añade aquí con su motivo, no se cuela.
"""
import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.core.datetime_utils import org_today_local

APPS_DIR = Path(__file__).resolve().parents[2]
EXCLUDED_PATH_PARTS = {'tests', 'migrations'}

MESSAGE = (
    "usa la fecha del SISTEMA en una regla de negocio. "
    "«Hoy» es el día local de la organización: "
    "`org_today_local(org)` o, en un validador de serializer, "
    "`serializer_today(self)` (apps.core.datetime_utils)."
)


def _is_calendar_violation(node):
    """`date.today()` o `datetime.now()` **naive**.

    Lo que se persigue son los relojes AMBIGUOS, no cualquier lectura de la
    hora. Dos formas quedan fuera a propósito, y la distinción importa porque
    el bug es sobre **días de calendario**, no sobre instantes:

    - `timezone.now()` (Django): *aware* en UTC. Es el punto de partida
      correcto — de hecho es lo que `org_now_local` usa por debajo.
    - `datetime.now(tz)` **con zona explícita**: también inequívoco. Lo usan
      el horario de atención del agente (con la zona de la org), el timestamp
      de un log de auditoría y la comprobación de sunset de un endpoint. Nada
      de eso pregunta «¿qué día es hoy para esta clínica?».

    Lo prohibido es preguntar la fecha sin decir en qué zona: ahí la respuesta
    la da el sistema operativo del servidor.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    attr = node.func.attr
    base = node.func.value
    # `X.today()` / `X.now()` → interesa qué es X.
    name = (base.attr if isinstance(base, ast.Attribute)
            else base.id if isinstance(base, ast.Name) else '')
    if attr == 'today':
        return name == 'date'
    if attr == 'now' and name == 'datetime':       # `timezone.now()` queda fuera
        return not node.args and not node.keywords  # …y `datetime.now(tz)` también
    return False


class CalendarRuleAuditTests(SimpleTestCase):

    def test_ninguna_regla_de_negocio_usa_la_fecha_del_sistema(self):
        violations = []
        for path in sorted(APPS_DIR.rglob('*.py')):
            if EXCLUDED_PATH_PARTS & set(path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:                      # pragma: no cover
                continue
            for node in ast.walk(tree):
                if _is_calendar_violation(node):
                    relative = path.relative_to(APPS_DIR.parent)
                    violations.append(f"{relative}:{node.lineno}")

        self.assertEqual(
            violations, [],
            f"{len(violations)} sitio(s) {MESSAGE}\n  " + "\n  ".join(violations),
        )


class CalendarRuleBehaviourTests(SimpleTestCase):
    """El defecto real, con el reloj congelado en el instante que lo produce.

    El gate de arriba impide que vuelva a escribirse `date.today()`. Esto
    demuestra POR QUÉ importa — sin un reloj fijo el caso solo se reproduce
    seis horas al día, que es justamente por qué nadie lo había visto.
    """

    # 2026-08-02, 00:30 UTC. En Ciudad de México (UTC−6) siguen siendo las
    # 18:30 del 1 de agosto: los dos calendarios están en días distintos.
    INSTANTE = datetime(2026, 8, 2, 0, 30, tzinfo=ZoneInfo('UTC'))

    def test_el_dia_local_de_la_clinica_no_es_el_del_servidor(self):
        mexico = SimpleNamespace(timezone='America/Mexico_City')
        utc = SimpleNamespace(timezone='UTC')

        with mock.patch('django.utils.timezone.now', return_value=self.INSTANTE):
            self.assertEqual(str(org_today_local(mexico)), '2026-08-01')
            self.assertEqual(str(org_today_local(utc)), '2026-08-02')

    def test_manana_de_la_clinica_es_hoy_en_utc(self):
        """El defecto exacto que se corrigió.

        A las 18:30 del 1 de agosto en México, `2026-08-02` es MAÑANA para esa
        clínica. Un validador que preguntara la fecha en UTC la vería como
        "hoy" y la aceptaría — así se colaba una vacuna fechada en el futuro
        dentro de un expediente clínico.
        """
        mexico = SimpleNamespace(timezone='America/Mexico_City')
        with mock.patch('django.utils.timezone.now', return_value=self.INSTANTE):
            hoy_clinica = org_today_local(mexico)
            manana_clinica = hoy_clinica + timedelta(days=1)

            self.assertGreater(manana_clinica, hoy_clinica)
            # …y es exactamente el día que UTC ya considera presente.
            self.assertEqual(str(manana_clinica), '2026-08-02')
