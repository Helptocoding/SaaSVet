"""
Guardia anti-leak de tenant isolation (ratchet por baseline).

Contexto: el aislamiento multitenant es convención — `TenantManager.get_queryset()`
NO filtra por organización (core/models.py); cada caller debe usar
`for_organization(org)`. Un `Model.objects.filter(...)` sin scoping puede leakear
cross-tenant sin error ni log (auditoría 2026-05-26, hallazgo C3). RLS DB-side se
difirió a post-beta (ADR p23). Este test es el control interino.

Qué hace: escanea el código de negocio (views/services/serializers) por accesos
DIRECTOS `<Model>.objects.<método-de-lectura>` que NO pasan por `for_organization`.
Detección AST precisa:
  - `Model.objects.filter(...)`                     -> FLAG
  - `Model.objects.for_organization(org).filter()`  -> safe (chained, func.value es Call)
  - `Model.all_objects.filter()`                     -> safe (no es '.objects.')
  - `qs.filter()`                                    -> safe (no es '.objects.')

Modelos no-tenant (User, Organization, RBAC, tokens JWT) y el módulo `platform`
(cross-org por rol ADMIN_SAAS) se excluyen.

Ratchet: el set actual debe ser IGUAL al BASELINE congelado. No reclama que el
baseline sea seguro — reclama que no se agreguen ocurrencias NUEVAS sin revisión.
- Ocurrencia nueva no en baseline -> FALLA: usar `for_organization` o, si es
  legítima (scoped por FK padre ya tenant-validado), agregar al BASELINE con
  revisión consciente.
- Ocurrencia eliminada (baseline stale) -> FALLA: quitarla del BASELINE.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

# .../backend/apps
APPS_DIR = Path(__file__).resolve().parents[2]

SCANNED_FILENAMES = {'views.py', 'services.py', 'serializers.py', 'selectors.py'}
EXCLUDED_TOP_MODULES = {'platform'}          # cross-org por diseño (ADMIN_SAAS)
EXCLUDED_PATH_PARTS = {'tests', 'migrations'}

READ_METHODS = {
    'filter', 'get', 'all', 'exclude', 'first', 'last', 'count', 'exists',
    'aggregate', 'annotate', 'values', 'values_list', 'iterator',
    'get_or_create', 'latest', 'earliest', 'in_bulk',
}

# Modelos NO scoped por organización (o raíz del tenant): lookups legítimos sin
# for_organization. No son OrganizationalModel-por-org o son el root del tenant.
NON_TENANT_MODELS = {
    'User', 'Organization', 'OrganizationSettings', 'OrganizationTimezoneAudit',
    'Permission', 'Role', 'UserRole',
    'OutstandingToken', 'BlacklistedToken',
    # ADR p46: LegalDocument es GLOBAL (sin FK a organization) — el texto legal
    # es único para todo el SaaS; no aplica for_organization por diseño.
    'LegalDocument',
}

# Baseline congelado: (módulo_top, archivo, modelo, método). Cada entrada es un
# acceso `<Model>.objects.<método>` EXISTENTE y revisado (scoped por FK padre
# tenant-validado, filtro org inline, get_or_create con organization en defaults,
# o interno de analytics por org). Ratchet: el scan actual debe ser exactamente
# este set. Ver docstring para cómo actualizar.
BASELINE = {
    ('analytics', 'services.py', 'DailyOrgMetrics', 'filter'),
    ('appointments', 'serializers.py', 'MedicalRecord', 'filter'),
    ('appointments', 'serializers.py', 'Invoice', 'filter'),
    ('appointments', 'serializers.py', 'Appointment', 'filter'),
    ('appointments', 'views.py', 'Appointment', 'filter'),
    ('appointments', 'views.py', 'MedicalRecord', 'filter'),
    ('appointments', 'views.py', 'MedicalRecord', 'get_or_create'),
    ('appointments', 'views.py', 'Owner', 'get_or_create'),
    ('billing', 'serializers.py', 'InvoiceItem', 'filter'),
    ('billing', 'services.py', 'Invoice', 'get_or_create'),
    ('inventory', 'serializers.py', 'Product', 'filter'),
    ('inventory', 'serializers.py', 'PrescriptionItem', 'filter'),
    ('inventory', 'views.py', 'StockMovement', 'filter'),
    ('inventory', 'views.py', 'InvoiceItem', 'filter'),
    ('inventory', 'views.py', 'MedicalRecordProduct', 'filter'),
    ('inventory', 'views.py', 'Product', 'filter'),
    # Revisado 2026-07-15 (inventory/services.py:420): get_or_create con
    # organization= explícito en el lookup — tenant-scoped por construcción.
    ('inventory', 'services.py', 'StockLot', 'get_or_create'),
    # Revisados 2026-07-15: LegalAcceptance se filtra/crea por user, y un user
    # pertenece a exactamente una organización (invariante ADR p48). El scoping
    # viene del principal autenticado, no de un id del cliente.
    ('legal', 'services.py', 'LegalAcceptance', 'filter'),
    ('legal', 'services.py', 'LegalAcceptance', 'get_or_create'),
    ('medical_records', 'views.py', 'Invoice', 'filter'),
    ('medical_records', 'views.py', 'MedicalRecordService', 'filter'),
    # Revisado 2026-07-15 (medical_records/services.py:136): scoped por FK padre
    # medical_record, obtenido org-scoped y bajo lock por el caller (cierre).
    ('medical_records', 'services.py', 'MedicalRecordProduct', 'filter'),
    ('patients', 'serializers.py', 'Owner', 'get_or_create'),
}


class _ObjectsAccessVisitor(ast.NodeVisitor):
    """Detecta `<Model>.objects.<READ_METHOD>(...)` directo (no chained tras for_organization)."""

    def __init__(self):
        self.findings = []  # (model_name, method)

    def visit_Call(self, node):
        func = node.func
        # func == `<receiver>.<method>`; method en READ_METHODS;
        # receiver == `<expr>.objects` (Attribute attr='objects') DIRECTO.
        if (
            isinstance(func, ast.Attribute)
            and func.attr in READ_METHODS
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == 'objects'
        ):
            model_expr = ast.unparse(func.value.value)
            model_name = model_expr.split('.')[-1]
            if model_name not in NON_TENANT_MODELS:
                self.findings.append((model_name, func.attr))
        self.generic_visit(node)


def _iter_business_files():
    for path in APPS_DIR.rglob('*.py'):
        if path.name not in SCANNED_FILENAMES:
            continue
        rel = path.relative_to(APPS_DIR)
        if rel.parts[0] in EXCLUDED_TOP_MODULES:
            continue
        if set(rel.parts) & EXCLUDED_PATH_PARTS:
            continue
        yield path, rel.parts[0]


def collect_findings():
    findings = set()
    for path, top_module in _iter_business_files():
        source = path.read_text(encoding='utf-8')
        visitor = _ObjectsAccessVisitor()
        visitor.visit(ast.parse(source))
        for model_name, method in visitor.findings:
            findings.add((top_module, path.name, model_name, method))
    return findings


class TenantScopingAuditTests(SimpleTestCase):
    def test_no_unbaselined_objects_access_without_for_organization(self):
        current = collect_findings()

        new = current - BASELINE
        stale = BASELINE - current

        msg = []
        if new:
            msg.append(
                "Accesos `.objects.<método>` NUEVOS sin for_organization "
                "(posible leak cross-tenant). Usa `for_organization(org)`; si es "
                "legítimo (scoped por FK padre tenant-validado), agrégalo al "
                "BASELINE con revisión:\n  "
                + "\n  ".join(repr(x) for x in sorted(new))
            )
        if stale:
            msg.append(
                "Entradas STALE en BASELINE (el código ya no las contiene). "
                "Quítalas del BASELINE:\n  "
                + "\n  ".join(repr(x) for x in sorted(stale))
            )
        self.assertFalse(msg, "\n\n".join(msg))
