"""Gates estáticos de la versión de sesión (ADR p65).

1. ``session_version`` solo la escribe ``bump_session_version``. Escritura =
   asignación a un atributo, argumento con nombre en una llamada que no sea de
   lectura, o cualquier cadena literal que la contenga (``update_fields``,
   ``bulk_update``, ``setattr``, ``values_list``, SQL). Leer el atributo es libre.
2. Los sitios productivos que emiten tokens son exactamente los clasificados:
   un sitio nuevo tiene que decidir si estampa la versión.
3. Cada operación productiva que incrementa la versión (directamente o por un
   helper privado) tiene su prueba de revocación con tokens reales.
4. Solo la autenticación emite un 401: es la premisa del reintento único del
   frontend (D14), que repite la petición sin saber si es un POST.

Alcance: Python productivo de ``backend/apps`` y ``backend/config``, sin pruebas
ni migraciones. Recorre el AST, no el texto. Límite conocido (riesgo R6 del
plan): una actualización con claves dinámicas (``update(**campos)``) no se ve.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[3]
ROOTS = (BACKEND / 'apps', BACKEND / 'config')
FIELD = 'session_version'
READ_CALLS = frozenset({'filter', 'exclude', 'get', 'Q'})

# (archivo, función o clase) → motivo. Toda mención por cadena o escritura
# fuera de esta lista hace fallar el gate.
ALLOWED_WRITERS = {
    ('apps/users/models.py', 'User'): 'declaración del campo',
    ('apps/users/models.py', 'User.save'): 'guarda: excluye o rechaza el campo',
    ('apps/users/services.py', 'bump_session_version'): 'la única escritura legítima',
    ('apps/core/authentication.py', 'session_version_matches'):
        'lectura: nombres de campo del log AUTH_SESSION_REVOKED',
}

# Sitios productivos que emiten tokens (`for_user(` o `get_token(`).
EXPECTED_MINTERS = {
    ('apps/users/serializers.py', 'EmailOrUsernameTokenObtainPairSerializer.get_token'):
        'login: estampa la versión',
    ('apps/users/services.py', 'change_password'): 'estampa la versión nueva',
    ('apps/agent/executor.py', 'mint_agent_token'):
        'cuenta de servicio: sin claim, su versión nunca se incrementa',
}


def _production_files():
    for root in ROOTS:
        for path in root.rglob('*.py'):
            parts = set(path.relative_to(BACKEND).parts)
            if parts & {'tests', 'migrations', '__pycache__'}:
                continue
            if path.name.startswith('test_'):
                continue
            yield path


def _docstring_nodes(tree):
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                nodes.add(id(body[0].value))
    return nodes


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ''


class _Scanner(ast.NodeVisitor):
    """Recorre un módulo registrando (línea, ámbito) de escrituras y emisiones."""

    def __init__(self, tree):
        self.scope = []
        self.writes = []
        self.minters = []
        self.docstrings = _docstring_nodes(tree)

    @property
    def qualname(self):
        return '.'.join(self.scope) or '<module>'

    def _enter(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _enter
    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def _check_target(self, target):
        if isinstance(target, ast.Attribute) and target.attr == FIELD:
            self.writes.append((target.lineno, self.qualname))
        elif isinstance(target, ast.Name) and target.id == FIELD:
            self.writes.append((target.lineno, self.qualname))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._check_target(element)

    def visit_Assign(self, node):
        for target in node.targets:
            self._check_target(target)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._check_target(node.target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._check_target(node.target)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = _call_name(node)
        if name not in READ_CALLS:
            for keyword in node.keywords:
                if keyword.arg == FIELD:
                    self.writes.append((node.lineno, self.qualname))
        if name in ('for_user', 'get_token') and isinstance(node.func, ast.Attribute):
            self.minters.append((node.lineno, self.qualname))
        self.generic_visit(node)

    def visit_Constant(self, node):
        if (
            isinstance(node.value, str)
            and FIELD in node.value
            and id(node) not in self.docstrings
        ):
            self.writes.append((node.lineno, self.qualname))


def scan(source):
    tree = ast.parse(source)
    scanner = _Scanner(tree)
    scanner.visit(tree)
    return scanner


class ScannerDetectsEveryWriteFormTests(SimpleTestCase):
    """El gate solo vale si detecta cada forma de escribir el campo."""

    WRITES = {
        'asignación': 'def f(u):\n    u.session_version = 3\n',
        'asignación aumentada': 'def f(u):\n    u.session_version += 1\n',
        'update()': 'def f(qs):\n    qs.update(session_version=0)\n',
        'create()': 'def f(m):\n    m.objects.create(session_version=5)\n',
        'update_fields': "def f(u):\n    u.save(update_fields=['session_version'])\n",
        'setattr': "def f(u):\n    setattr(u, 'session_version', 1)\n",
        'bulk_update': "def f(qs, objs):\n    qs.bulk_update(objs, ['session_version'])\n",
        'SQL': "def f(c):\n    c.execute('UPDATE users_user SET session_version = 0')\n",
    }
    READS = {
        'atributo': 'def f(u):\n    return u.session_version\n',
        'filter()': 'def f(qs):\n    return qs.filter(session_version=1)\n',
        'docstring': 'def f():\n    """Habla de session_version."""\n',
    }

    def test_writes_are_detected(self):
        for label, source in self.WRITES.items():
            with self.subTest(label):
                self.assertTrue(scan(source).writes, f'no detectó: {label}')

    def test_reads_are_not_writes(self):
        for label, source in self.READS.items():
            with self.subTest(label):
                self.assertEqual(scan(source).writes, [], f'falso positivo: {label}')

    def test_minting_calls_are_detected(self):
        scanner = scan(
            'def a(u):\n    return RefreshToken.for_user(u)\n'
            'class S:\n    def get_token(cls, u):\n        return super().get_token(u)\n'
        )
        self.assertEqual({q for _, q in scanner.minters}, {'a', 'S.get_token'})


class SessionVersionWritersGateTests(SimpleTestCase):
    def test_only_bump_session_version_writes_the_field(self):
        violations = []
        for path in _production_files():
            rel = path.relative_to(BACKEND).as_posix()
            scanner = scan(path.read_text(encoding='utf-8'))
            for lineno, qualname in scanner.writes:
                if (rel, qualname) not in ALLOWED_WRITERS:
                    violations.append(f'{rel}:{lineno} ({qualname})')
        self.assertEqual(
            violations, [],
            'session_version solo se escribe con bump_session_version (ADR p65). '
            'Si es una lectura por cadena, clasifícala en ALLOWED_WRITERS.',
        )

    def test_allowed_writers_still_exist(self):
        found = set()
        for path in _production_files():
            rel = path.relative_to(BACKEND).as_posix()
            found.update((rel, q) for _, q in scan(path.read_text(encoding='utf-8')).writes)
        self.assertEqual(set(ALLOWED_WRITERS) - found, set())


class TokenMintingSitesGateTests(SimpleTestCase):
    def test_minting_sites_are_exactly_the_classified_ones(self):
        found = set()
        for path in _production_files():
            rel = path.relative_to(BACKEND).as_posix()
            found.update((rel, q) for _, q in scan(path.read_text(encoding='utf-8')).minters)
        self.assertEqual(
            found, set(EXPECTED_MINTERS),
            'Un sitio que emite tokens debe decidir si estampa la versión de sesión '
            '(ADR p65) y quedar clasificado en EXPECTED_MINTERS.',
        )


# ---------------------------------------------------------------------------
# 3. Toda operación que incrementa la versión tiene su prueba de revocación
# ---------------------------------------------------------------------------

BUMP = 'bump_session_version'

# Operación productiva → prueba de EveryBumpPathRevokesTests (test_session_version)
# que demuestra con tokens reales que el access y el refresh anteriores dejan de
# leer, escribir y renovarse después de ella.
BUMP_OPERATIONS = {
    ('apps/users/services.py', 'change_password'): 'test_change_password',
    ('apps/users/services.py', 'reset_password_for_staff'): 'test_clinic_reset',
    ('apps/users/services.py', 'deactivate_staff'): 'test_deactivate',
    ('apps/users/services.py', 'reactivate_staff'): 'test_reactivate',
    ('apps/platform/services/platform_reset_password.py', 'platform_reset_password'):
        'test_platform_reset',
}


class _CallGraph(ast.NodeVisitor):
    """Nombres que llama cada función o método, por su nombre calificado."""

    def __init__(self):
        self.scope = []
        self.calls = {}

    def _enter(self, node):
        self.scope.append(node.name)
        self.calls.setdefault('.'.join(self.scope), set())
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _enter
    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def visit_Call(self, node):
        if self.scope:
            self.calls['.'.join(self.scope)].add(_call_name(node))
        self.generic_visit(node)


def _short(qualname):
    return qualname.rsplit('.', 1)[-1]


def bump_operations(modules):
    """Funciones públicas que incrementan la versión: llaman a ``BUMP`` o a un
    helper privado (``_x``) que la incrementa, en cualquier profundidad.

    ``modules``: iterable de ``(ruta relativa, código fuente)``.
    """
    graph = {}
    for rel, source in modules:
        visitor = _CallGraph()
        visitor.visit(ast.parse(source))
        for qualname, names in visitor.calls.items():
            graph[(rel, qualname)] = names

    reaches = {BUMP}
    changed = True
    while changed:
        changed = False
        for (_, qualname), names in graph.items():
            name = _short(qualname)
            if name.startswith('_') and name not in reaches and names & reaches:
                reaches.add(name)
                changed = True
    return {
        key for key, names in graph.items()
        if names & reaches and not _short(key[1]).startswith('_') and _short(key[1]) != BUMP
    }


def _production_modules():
    for path in _production_files():
        yield path.relative_to(BACKEND).as_posix(), path.read_text(encoding='utf-8')


class BumpOperationsGateTests(SimpleTestCase):
    def test_call_graph_follows_private_helpers(self):
        source = (
            'def _deep(u):\n    bump_session_version(u)\n'
            'def _mid(u):\n    _deep(u)\n'
            'def operation(u):\n    _mid(u)\n'
            'class Service:\n    def run(self, u):\n        bump_session_version(u)\n'
            'def unrelated(u):\n    u.save()\n'
        )
        self.assertEqual(
            bump_operations([('m.py', source)]),
            {('m.py', 'operation'), ('m.py', 'Service.run')},
        )

    def test_every_operation_that_bumps_is_classified(self):
        self.assertEqual(
            bump_operations(_production_modules()), set(BUMP_OPERATIONS),
            'Una operación nueva que incrementa la versión de sesión necesita su '
            'prueba de revocación en EveryBumpPathRevokesTests y su entrada en '
            'BUMP_OPERATIONS (ADR p65).',
        )

    def test_every_classified_operation_has_its_revocation_test(self):
        # Importado aquí y no arriba: en el módulo lo descubriría el runner otra vez.
        from apps.users.tests.test_session_version import EveryBumpPathRevokesTests

        for operation, test_name in BUMP_OPERATIONS.items():
            with self.subTest(operation=operation):
                self.assertTrue(
                    callable(getattr(EveryBumpPathRevokesTests, test_name, None)),
                    f'Falta EveryBumpPathRevokesTests.{test_name}',
                )


# ---------------------------------------------------------------------------
# 4. Solo la autenticación emite 401 (premisa del reintento D14)
# ---------------------------------------------------------------------------

UNAUTHORIZED_NAMES = frozenset({
    'AuthenticationFailed', 'NotAuthenticated', 'SessionRevoked', 'HTTP_401_UNAUTHORIZED',
})

# Sitio → por qué ocurre antes de ejecutar cualquier vista (o en una ruta que el
# frontend nunca reintenta).
EXPECTED_401_SITES = {
    ('apps/core/authentication.py', 'SessionRevoked'): 'declaración de la excepción',
    ('apps/core/authentication.py', 'TenantJWTAuthentication.authenticate'):
        'autenticación de DRF: corre antes del handler de la vista',
    ('config/urls.py', 'PublicTokenRefreshView.post'):
        'token/refresh/: excluido del reintento en api/client.js',
}


class _UnauthorizedScanner(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.sites = []

    def _enter(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _enter
    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def _hit(self, node):
        self.sites.append((node.lineno, '.'.join(self.scope) or '<module>'))

    def visit_Name(self, node):
        if node.id in UNAUTHORIZED_NAMES:
            self._hit(node)

    def visit_Attribute(self, node):
        if node.attr in UNAUTHORIZED_NAMES:
            self._hit(node)
        self.generic_visit(node)

    def visit_keyword(self, node):
        if node.arg in ('status', 'status_code') and getattr(node.value, 'value', None) == 401:
            self._hit(node.value)
        self.generic_visit(node)

    def visit_Assign(self, node):
        if getattr(node.value, 'value', None) == 401 and any(
            getattr(t, 'id', getattr(t, 'attr', None)) == 'status_code' for t in node.targets
        ):
            self._hit(node)
        self.generic_visit(node)


def unauthorized_sites(source):
    scanner = _UnauthorizedScanner()
    scanner.visit(ast.parse(source))
    return scanner.sites


class OnlyAuthenticationEmits401GateTests(SimpleTestCase):
    def test_scanner_detects_every_form(self):
        forms = {
            'raise': 'def f():\n    raise AuthenticationFailed("x")\n',
            'subclase': 'class E(NotAuthenticated):\n    pass\n',
            'constante DRF': 'def f():\n    return Response({}, status=status.HTTP_401_UNAUTHORIZED)\n',
            'entero': 'def f():\n    return Response({}, status=401)\n',
            'status_code': 'class E(APIException):\n    status_code = 401\n',
        }
        for label, source in forms.items():
            with self.subTest(label):
                self.assertTrue(unauthorized_sites(source), f'no detectó: {label}')
        self.assertEqual(
            unauthorized_sites('from rest_framework.exceptions import AuthenticationFailed\n'), [],
        )

    def test_401_only_comes_from_authentication(self):
        found = set()
        for rel, source in _production_modules():
            found.update((rel, q) for _, q in unauthorized_sites(source))
        self.assertEqual(
            found, set(EXPECTED_401_SITES),
            'El frontend repite una vez un 401 con un token ya renovado sin mirar el '
            'método (D14, ADR p65). Un 401 emitido después de ejecutar la vista '
            'repetiría su efecto: clasifícalo aquí solo si ocurre antes de la vista '
            'o en una ruta que api/client.js no reintenta.',
        )
