"""
Ratchet de contención de la deuda id/public_id (ADR p24).

~10 serializers de modelos públicos exponen el PK entero `id` junto a `public_id`
en `Meta.fields`. Removerlos ahora es un contract change rompedor acoplado al
frontend (diferido). Este test CONTIENE la deuda: el set actual es el baseline
congelado; un serializer NUEVO que exponga `id`+`public_id` falla el test.

Política (ADR p24):
- Nuevo serializer de modelo con public_id -> exponer SOLO `public_id`, nunca `id`.
- Legacy -> tolerado en BASELINE temporalmente.
- Salida futura: migrar frontend a publicId, remover `id` fase por fase, vaciar baseline.

Detección AST: ClassDef con `Meta.fields` cuyo RHS contiene los literales 'id' Y
'public_id'. Serializers de modelos internos (InvoiceItem, VitalSigns, etc.) exponen
solo 'id' (no tienen public_id) -> NO se flaggean.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

# .../backend/apps
APPS_DIR = Path(__file__).resolve().parents[2]
EXCLUDED_PATH_PARTS = {'tests', 'migrations'}

# Serializers que HOY exponen id+public_id (deuda legacy tolerada). Ratchet: el
# scan actual debe ser exactamente este set. Nuevo -> falla (exponer solo
# public_id). Removido -> falla (quitar del baseline). Ver ADR p24.
BASELINE = {
    ('appointments', 'serializers.py', 'AppointmentSerializer'),
    ('billing', 'serializers.py', 'InvoiceSerializer'),
    ('billing', 'serializers.py', 'ServiceSerializer'),
    ('inventory', 'serializers.py', 'PresentationSerializer'),
    ('inventory', 'serializers.py', 'ProductSerializer'),
    ('medical_records', 'serializers.py', 'MedicalRecordSerializer'),
    ('medical_records', 'serializers.py', 'VaccineRecordSerializer'),
    ('organizations', 'serializers.py', 'OrganizationSerializer'),
    ('patients', 'serializers.py', 'OwnerSerializer'),
    ('patients', 'serializers.py', 'PetSerializer'),
    ('prescriptions', 'serializers.py', 'PrescriptionSerializer'),
    ('users', 'serializers.py', 'UserSerializer'),
}


def _collect_str_constants(node):
    return {
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


class _SerializerVisitor(ast.NodeVisitor):
    def __init__(self):
        self.findings = []  # class names exposing id + public_id

    def visit_ClassDef(self, node):
        for inner in node.body:
            if isinstance(inner, ast.ClassDef) and inner.name == 'Meta':
                for stmt in inner.body:
                    if isinstance(stmt, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == 'fields' for t in stmt.targets
                    ):
                        strings = _collect_str_constants(stmt.value)
                        if {'id', 'public_id'} <= strings:
                            self.findings.append(node.name)
        self.generic_visit(node)


def _iter_serializer_files():
    for path in APPS_DIR.rglob('serializers.py'):
        rel = path.relative_to(APPS_DIR)
        if set(rel.parts) & EXCLUDED_PATH_PARTS:
            continue
        yield path, rel.parts[0]


def collect_findings():
    findings = set()
    for path, top_module in _iter_serializer_files():
        source = path.read_text(encoding='utf-8')
        visitor = _SerializerVisitor()
        visitor.visit(ast.parse(source))
        for class_name in visitor.findings:
            findings.add((top_module, path.name, class_name))
    return findings


class PublicIdDualExposureAuditTests(SimpleTestCase):
    def test_no_new_serializer_exposes_id_and_public_id(self):
        current = collect_findings()

        new = current - BASELINE
        stale = BASELINE - current

        msg = []
        if new:
            msg.append(
                "Serializer(s) NUEVO(s) exponiendo `id`+`public_id` (deuda híbrida, "
                "ADR p24). Nuevo código: expón SOLO `public_id`. Si es legacy "
                "legítimo, agrégalo al BASELINE con revisión:\n  "
                + "\n  ".join(repr(x) for x in sorted(new))
            )
        if stale:
            msg.append(
                "Entradas STALE en BASELINE (ya no exponen id+public_id — bien, "
                "deuda pagada). Quítalas del BASELINE:\n  "
                + "\n  ".join(repr(x) for x in sorted(stale))
            )
        self.assertFalse(msg, "\n\n".join(msg))
