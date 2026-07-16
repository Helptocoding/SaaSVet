"""
test_permissions_catalog.py — É0-PR1 (plan de épicas del agente WhatsApp).

Guards de consistencia del catálogo RBAC (`apps/core/permissions_codes.py`).

Origen: el gap `vaccinerecord` — las views declaraban
`resource_name="vaccinerecord"` (Día 6/ADR p18) pero el catálogo nunca tuvo
códigos `vaccinerecord.*`, así que `HybridPermission` exigía un permiso que
ningún rol podía tener → VET/ASSISTANT con UserRole en DB recibían
RBAC_DENIED; solo ADMIN (`*.*`) y superuser pasaban. Nadie lo notó porque el
CI corría 0 tests (apps/ sin __init__.py, corregido en e73fa94).

Tres guards:
  1. Views→catálogo (el que atrapa la clase de bug real): todo
     `resource_name`, `make_permission("x.y")` y `required_permission = "x.y"`
     de las views debe existir en PERMISSION_CODES.
  2. Dict→catálogo: todo código asignado en PERMISSIONS existe en
     PERMISSION_CODES (o es el wildcard global).
  3. Catálogo sin duplicados.

Mismo estilo AST/ratchet que test_tenant_scoping_audit y
test_public_id_dual_exposure_audit.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS

# .../backend/apps
APPS_DIR = Path(__file__).resolve().parents[2]
EXCLUDED_PATH_PARTS = {'tests', 'migrations'}
# platform usa IsPlatformOperator (permission class propia, no códigos RBAC).
EXCLUDED_TOP_MODULES = {'platform'}


def _iter_view_files():
    for path in APPS_DIR.rglob('views.py'):
        rel = path.relative_to(APPS_DIR)
        if EXCLUDED_PATH_PARTS.intersection(rel.parts):
            continue
        if rel.parts[0] in EXCLUDED_TOP_MODULES:
            continue
        yield rel.parts[0], path


class _PermissionRefVisitor(ast.NodeVisitor):
    """Recolecta referencias a permisos en una views.py:
    - resource_name = "<recurso>"        → self.resources
    - make_permission("x.y")             → self.exact_codes
    - required_permission = "x.y"        → self.exact_codes
    """

    def __init__(self):
        self.resources = set()
        self.exact_codes = set()

    def visit_Assign(self, node):
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in node.targets:
                name = getattr(target, 'id', None) or getattr(target, 'attr', None)
                if name == 'resource_name':
                    self.resources.add(value.value)
                elif name == 'required_permission':
                    self.exact_codes.add(value.value)
        self.generic_visit(node)

    def visit_Call(self, node):
        func_name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
        if func_name == 'make_permission' and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self.exact_codes.add(arg.value)
        self.generic_visit(node)


def _collect_view_permission_refs():
    resources, exact_codes = set(), set()
    for module, path in _iter_view_files():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        visitor = _PermissionRefVisitor()
        visitor.visit(tree)
        resources.update((module, r) for r in visitor.resources)
        exact_codes.update((module, c) for c in visitor.exact_codes)
    return resources, exact_codes


class PermissionsCatalogConsistencyTests(SimpleTestCase):

    def test_scanner_is_not_vacuous(self):
        """El scanner AST realmente encuentra referencias (anti-vacuidad).

        Lección del propio bug que motivó este archivo: un guard que escanea
        cero elementos "pasa" para siempre. Si este test falla, el visitor
        dejó de reconocer los patrones (p.ej. cambió la convención de las
        views) y TODOS los demás tests de este archivo son papel mojado.
        """
        resources, exact = _collect_view_permission_refs()
        self.assertIn(('appointments', 'appointment'), resources)
        self.assertIn(('medical_records', 'vaccinerecord'), resources)
        self.assertTrue(
            any(code == 'medicalrecord.close' for _, code in exact),
            "make_permission('medicalrecord.close') no detectado — visitor roto",
        )

    def test_view_resource_names_have_catalog_codes(self):
        """Todo resource_name de una view tiene ≥1 código en el catálogo.

        Este es el guard que habría atrapado el gap vaccinerecord: una view
        que exige `<recurso>.<acción>` sin que exista NINGÚN código de ese
        recurso = recurso inaccesible para todo rol sin wildcard.
        """
        prefixes = {code.split('.')[0] for code in PERMISSION_CODES}
        resources, _ = _collect_view_permission_refs()
        missing = sorted(
            f"{module}/views.py: resource_name='{r}' sin códigos '{r}.*' en PERMISSION_CODES"
            for module, r in resources if r not in prefixes
        )
        self.assertFalse(missing, '\n'.join(missing))

    def test_view_exact_permission_codes_exist_in_catalog(self):
        """make_permission("x.y") y required_permission="x.y" existen en el catálogo."""
        catalog = set(PERMISSION_CODES) | {"*.*"}
        _, exact = _collect_view_permission_refs()
        missing = sorted(
            f"{module}/views.py: código '{c}' no existe en PERMISSION_CODES"
            for module, c in exact if c not in catalog
        )
        self.assertFalse(missing, '\n'.join(missing))

    def test_all_role_assignments_exist_in_catalog(self):
        """Todo código asignado a un rol en PERMISSIONS existe en el catálogo."""
        catalog = set(PERMISSION_CODES) | {"*.*"}
        problems = []
        for role, codes in PERMISSIONS.items():
            unknown = [c for c in codes if c not in catalog]
            if unknown:
                problems.append(f"Rol {role}: {unknown}")
        self.assertFalse(problems, '\n'.join(problems))

    def test_catalog_has_no_duplicates(self):
        dupes = [c for c in set(PERMISSION_CODES) if PERMISSION_CODES.count(c) > 1]
        self.assertFalse(dupes, f"Códigos duplicados en PERMISSION_CODES: {dupes}")
