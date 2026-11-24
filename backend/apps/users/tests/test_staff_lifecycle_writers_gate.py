"""Gate estático: escritores de ``is_active=False``, ``role`` e ``is_service_account``.

Invariante (plan Equipo, II.3.1): una organización nunca queda sin al menos un
ADMIN activo como consecuencia de una operación de gestión de personal. Hoy
``deactivate_staff`` es la única vía del producto que reduce el conjunto de
ADMIN activos, y la protege un bloqueo ordenado. Este gate mantiene esa
afirmación verdadera: enumera cada sitio productivo que escribe esos campos y
falla si aparece uno sin clasificar (o si una clasificación ya no existe).

El criterio de cuenta de servicio es ``is_service_account`` (ADR p51/p65): por
eso sus escritores también están aquí.

Fuera del gate, a propósito: el admin de Django y la shell (vía de operadores).
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[3]
ROOTS = (BACKEND / 'apps', BACKEND / 'config')
READ_CALLS = frozenset({
    'filter', 'exclude', 'get', 'Q', 'select_for_update', 'values',
    'values_list', 'annotate', 'order_by',
})

CREATION = 'crea un usuario: solo puede aumentar los ADMIN activos'
USER_ROLE = 'escribe UserRole.role, no User.role'

CLASSIFIED = {
    ('apps/users/services.py', 'deactivate_staff', 'is_active=False'):
        'User: protegido por el bloqueo y la regla del último ADMIN',
    ('apps/billing/models.py', 'CheckoutItem.delete', 'is_active=False'): 'otro modelo',
    ('apps/patients/archive.py', 'change_archive_state', 'is_active=False'):
        'otro modelo (Pet/Owner)',
    ('apps/users/services.py', 'create_staff_member', 'role'): CREATION,
    ('apps/platform/services/provision_organization.py', 'provision_organization', 'role'):
        CREATION + '; también ' + USER_ROLE,
    ('apps/users/bootstrap.py', 'bootstrap_platform_superuser', 'role'):
        'crea el operador de plataforma (ADMIN_SAAS)',
    ('apps/core/management/commands/seed_demo_clinic.py', 'Command._ensure_users', 'role'):
        CREATION + ' (demo)',
    ('apps/agent/management/commands/agent_eval.py', 'Command._seed', 'role'):
        CREATION + ' (eval revertida)',
    ('apps/users/services.py', 'ensure_agent_user', 'role'):
        'crea la cuenta de servicio del agente; también ' + USER_ROLE,
    ('apps/users/services.py', 'ensure_agent_user', 'is_service_account'):
        'único escritor del criterio de cuenta de servicio, al crearla',
    ('apps/users/management/commands/migrate_users_to_roles.py', 'Command.handle', 'role'): USER_ROLE,
    ('apps/users/services.py', '_assign_system_role', 'role'): USER_ROLE,
    ('apps/users/signals.py', 'assign_rbac_role_on_create', 'role'): USER_ROLE,
}


def _production_files():
    for root in ROOTS:
        for path in root.rglob('*.py'):
            parts = set(path.relative_to(BACKEND).parts)
            if parts & {'tests', 'migrations', '__pycache__'} or path.name.startswith('test_'):
                continue
            yield path


def _is_false(node):
    return isinstance(node, ast.Constant) and node.value is False


class _Scanner(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.found = set()

    def _enter(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _enter
    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def _record(self, kind):
        self.found.add(('.'.join(self.scope) or '<module>', kind))

    def _target(self, target, value):
        if not isinstance(target, ast.Attribute):
            return
        if target.attr == 'is_active' and _is_false(value):
            self._record('is_active=False')
        elif target.attr in ('role', 'is_service_account'):
            self._record(target.attr)

    def visit_Assign(self, node):
        for target in node.targets:
            self._target(target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._target(node.target, None)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
        if name not in READ_CALLS:
            for keyword in node.keywords:
                if keyword.arg == 'is_active' and _is_false(keyword.value):
                    self._record('is_active=False')
                elif keyword.arg in ('role', 'is_service_account'):
                    self._record(keyword.arg)
        self.generic_visit(node)


def scan(source):
    scanner = _Scanner()
    scanner.visit(ast.parse(source))
    return scanner.found


class ScannerDetectsWritesTests(SimpleTestCase):
    def test_detects_each_form(self):
        cases = {
            'asignación is_active': ('def f(u):\n    u.is_active = False\n', 'is_active=False'),
            'update is_active': ('def f(qs):\n    qs.update(is_active=False)\n', 'is_active=False'),
            'asignación role': ("def f(u):\n    u.role = 'ADMIN'\n", 'role'),
            'update role': ("def f(qs):\n    qs.update(role='VET')\n", 'role'),
            'is_service_account': ('def f(u):\n    u.is_service_account = True\n', 'is_service_account'),
        }
        for label, (source, kind) in cases.items():
            with self.subTest(label):
                self.assertIn(('f', kind), scan(source))

    def test_reads_and_activations_are_not_writes(self):
        sources = (
            "def f(qs):\n    return qs.filter(is_active=False, role='ADMIN')\n",
            'def f(u):\n    u.is_active = True\n',
            'def f(u):\n    return u.role\n',
        )
        for source in sources:
            with self.subTest(source):
                self.assertEqual(scan(source), set())


class LifecycleWritersGateTests(SimpleTestCase):
    def test_writers_are_exactly_the_classified_ones(self):
        found = set()
        for path in _production_files():
            rel = path.relative_to(BACKEND).as_posix()
            found.update((rel, qualname, kind) for qualname, kind in scan(path.read_text(encoding='utf-8')))
        unclassified = sorted(found - set(CLASSIFIED))
        stale = sorted(set(CLASSIFIED) - found)
        self.assertEqual(
            unclassified, [],
            'Escritor nuevo de is_active=False, role o is_service_account. Si puede '
            'reducir los ADMIN activos, debe usar el bloqueo de deactivate_staff '
            '(plan Equipo, II.3.1); después clasifícalo aquí.',
        )
        self.assertEqual(stale, [], 'Clasificación sin sitio: quítala de CLASSIFIED.')
