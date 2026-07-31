"""
test_arbiter.py — É-F4 Fase 3 (ADR p55 §2): los cinco presupuestos del árbitro.

Estos tests no comprueban que el árbitro *funcione*: comprueban que **siga
siendo un árbitro**. La objeción que los motiva es la correcta — si en seis
meses tiene 500 líneas de reglas especiales, excepciones y prioridades, solo
se movió la complejidad de sitio.

No es una preocupación hipotética: ya pasó en esta casa con esta misma capa.
`policy.evaluate` nació como "un router de predicados en el orden exacto de la
spec" y hoy tiene 203 líneas, 20 pasos —seis metidos con calzador, que la
numeración `2b/6b/8b/8c/10b/12b` conserva como registro fósil— y seis `save()`
dentro de una función documentada como pura. Nadie decidió eso; llegó un
sufijo `b` a la vez.

Los cinco nacen en el primer commit a propósito: un presupuesto añadido
después no se añade nunca.
"""
import ast
import inspect

from django.test import SimpleTestCase

from apps.agent import arbiter


def _decide_ast():
    tree = ast.parse(inspect.getsource(arbiter.decide))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == 'decide')


def _has_docstring(node):
    return (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str))


def _module_ast():
    with open(arbiter.__file__, encoding='utf-8') as fh:
        return ast.parse(fh.read())


class A1ClosedVerdictSetTests(SimpleTestCase):
    """El espacio de SALIDA es lo que fija la complejidad de una capa de
    decisión, no el de entrada. Un sexto veredicto exige un ADR."""

    def test_there_are_exactly_five_verdicts(self):
        self.assertEqual(len(arbiter.VERDICTS), 5)
        self.assertEqual(len(set(arbiter.VERDICTS)), 5)

    def test_the_five_are_the_ones_the_adr_names(self):
        self.assertEqual(
            set(arbiter.VERDICTS),
            {'continuar', 'desviar', 'suplantar', 'abortar', 'responder'})

    def test_decide_only_ever_returns_one_of_them(self):
        combos = [
            arbiter.TurnFacts(),
            arbiter.TurnFacts(interrupts=True),
            arbiter.TurnFacts(client_declined=True),
            arbiter.TurnFacts(proposes_other_commitment=True),
            arbiter.TurnFacts(interrupts=True, client_declined=True,
                              proposes_other_commitment=True),
        ]
        view = arbiter.CommitmentView('family_challenge', 'digits')
        for facts in combos:
            for commitment in (view, None):
                with self.subTest(facts=facts, commitment=commitment):
                    self.assertIn(
                        arbiter.decide(facts, commitment).verdict,
                        arbiter.VERDICTS)


class A2PureFunctionTests(SimpleTestCase):
    """Cero DB, cero red, cero efectos.

    `SimpleTestCase` prohíbe el acceso a la base: si `decide` tocara el ORM,
    Django levantaría aquí. No es cosmético — los seis `save()` de
    `policy.evaluate` son la razón de que sus pasos no se puedan reordenar,
    probar por separado ni tabular.
    """

    def test_decide_runs_without_database_access(self):
        verdict = arbiter.decide(
            arbiter.TurnFacts(interrupts=True),
            arbiter.CommitmentView('identity_challenge', 'pet'))
        self.assertEqual(verdict.verdict, arbiter.DEVIATE)

    def test_decide_does_not_mutate_its_inputs(self):
        facts = arbiter.TurnFacts(interrupts=True)
        view = arbiter.CommitmentView('family_challenge', 'digits')
        arbiter.decide(facts, view)
        self.assertEqual(facts, arbiter.TurnFacts(interrupts=True))
        self.assertEqual(
            view, arbiter.CommitmentView('family_challenge', 'digits'))

    def test_same_input_same_verdict(self):
        facts = arbiter.TurnFacts(client_declined=True)
        view = arbiter.CommitmentView('schedule_appointment', 'date')
        self.assertEqual(arbiter.decide(facts, view),
                         arbiter.decide(facts, view))


class A3FactsAsInputTests(SimpleTestCase):
    """Recibe hechos ya calculados. Cuando aparezca un caso nuevo, lo que
    crece es la lista de hechos y los matchers que los producen — no las
    ramas del árbitro. Que la complejidad migre a `matchers.py` es el diseño
    funcionando: crecer en una lista plana es salud, crecer en una decisión
    ramificada es decadencia."""

    _FORBIDDEN = ('matchers', 'models', 'django', 'policy', 'tools',
                  'planner', 'goals', 'identity', 'tier0', 'prompts')

    def test_the_module_imports_nothing_it_should_not(self):
        imported = set()
        for node in ast.walk(_module_ast()):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
                imported.update(a.name for a in node.names)
        for name in self._FORBIDDEN:
            with self.subTest(name=name):
                self.assertNotIn(name, imported)

    def test_decide_calls_nothing_but_its_own_result_type(self):
        called = {n.func.id for n in ast.walk(_decide_ast())
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertEqual(called, {'TurnVerdict'})


class A4BranchBudgetTests(SimpleTestCase):
    """Suena tosco; es lo único que funciona contra la deriva de seis meses.
    El repo ya bloquea CI con gates de este tipo (`noConsoleTokenLeak`, el de
    `.public_id || .id`). Sin esto, A1-A3 son recomendaciones."""

    # 4 reglas hoy + 2 de margen. Rebasarlo no es "subir el número": es la
    # señal de que un hecho está mal modelado (A5) o de que hace falta un ADR.
    BUDGET = 6

    def test_decide_stays_within_its_branch_budget(self):
        branching = [n for n in ast.walk(_decide_ast())
                     if isinstance(n, (ast.If, ast.IfExp, ast.BoolOp,
                                       ast.Match, ast.For, ast.While))]
        self.assertLessEqual(
            len(branching), self.BUDGET,
            f"`decide` tiene {len(branching)} ramas (presupuesto "
            f"{self.BUDGET}). Antes de subir el número: ¿el caso nuevo es un "
            f"HECHO que falta en TurnFacts, o de verdad un veredicto nuevo "
            f"(que exige ADR)?")

    def test_the_arbiter_still_fits_in_a_table(self):
        """Métrica de salud del ADR: si el árbitro no cabe en una tabla,
        dejó de ser un árbitro."""
        body = inspect.getsource(arbiter.decide).splitlines()
        code = [ln for ln in body
                if ln.strip() and not ln.strip().startswith('#')]
        self.assertLessEqual(len(code), 40)


class A5NoInternalPrecedenceTests(SimpleTestCase):
    """La única precedencia real del sistema (urgencia primero) vive ARRIBA,
    en las salvaguardas. Si el árbitro pudiera razonar sobre la urgencia, la
    urgencia pasaría a ser una cuestión de política — y no puede serlo: un
    cortacircuito no es una decisión, es la negativa a tener esa decisión."""

    _SAFEGUARD_WORDS = (
        'emergency', 'urgencia', 'urgent', 'opt_out', 'optout', 'blocked',
        'human_active', 'handoff', 'escalate', 'priority', 'prioridad',
    )

    def test_the_arbiter_knows_nothing_about_safeguards(self):
        """Mira el CÓDIGO, no la prosa: un docstring que explique *por qué*
        aquí no hay precedencia es justo lo que se quiere permitir."""
        node = _decide_ast()
        body = node.body[1:] if _has_docstring(node) else node.body
        code = '\n'.join(ast.unparse(stmt) for stmt in body).lower()
        for word in self._SAFEGUARD_WORDS:
            with self.subTest(word=word):
                self.assertNotIn(word, code)

    def test_safeguards_still_run_before_the_arbiter_is_consulted(self):
        """`policy.evaluate` resuelve urgencia, bloqueo, humano activo y
        opt-out ANTES de que ningún reto avance."""
        from apps.agent import policy
        source = inspect.getsource(policy.evaluate)
        for guard in ('is_emergency', 'is_blocked', 'STATE_HUMAN_ACTIVE',
                      'wants_optout'):
            self.assertLess(
                source.index(guard), source.index('get_identity_commitment'),
                f"La salvaguarda {guard} dejó de correr antes del árbitro.")


class ArbiterVerdictTests(SimpleTestCase):
    """Que además decida bien. Cada caso es uno real de la auditoría."""

    def setUp(self):
        self.view = arbiter.CommitmentView('family_challenge', 'digits')

    def test_no_commitment_means_just_answer(self):
        self.assertEqual(
            arbiter.decide(arbiter.TurnFacts(), None).verdict, arbiter.ANSWER)

    def test_a_question_without_the_answer_deviates(self):
        """Conv 13: "¿para qué necesitas eso?" en la etapa de los dígitos.
        Antes contaba como respuesta equivocada, dos veces, y cerró la
        puerta a un cliente que tenía los 4 factores correctos."""
        verdict = arbiter.decide(
            arbiter.TurnFacts(interrupts=True), self.view)
        self.assertEqual(verdict.verdict, arbiter.DEVIATE)
        # …y con la coordenada de vuelta: un desvío sin dirección de retorno
        # es una interrupción sobrevivida por suerte (R4).
        self.assertEqual(verdict.return_to, 'digits')
        self.assertEqual(verdict.commitment, 'family_challenge')

    def test_an_answer_continues(self):
        self.assertEqual(
            arbiter.decide(arbiter.TurnFacts(), self.view).verdict,
            arbiter.CONTINUE)

    def test_a_declining_client_aborts(self):
        self.assertEqual(
            arbiter.decide(
                arbiter.TurnFacts(client_declined=True), self.view).verdict,
            arbiter.ABORT)

    def test_another_commitment_supplants(self):
        """El perro que convulsiona a mitad de agendar NO abandonó la cita."""
        self.assertEqual(
            arbiter.decide(
                arbiter.TurnFacts(proposes_other_commitment=True),
                self.view).verdict,
            arbiter.SUPPLANT)
