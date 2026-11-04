"""Un hijo de una consulta CERRADA se puede anotar, no reescribir.

Origen (auditoría run-1, hallazgo
`medical_records/post-close-immutability-missing-on-vaccine-and-prescription-records`):

La inmutabilidad post-cierre se aplicaba a mano, vista por vista, con dos
helpers —`assert_can_modify_charges` para los cargos y
`assert_can_modify_medical_record` para los vitales— y el registro vacunal y la
receta nunca se conectaron a ninguno de los dos. Quedaban editables, después de
cerrar el expediente y sin dejar rastro, el paciente al que pertenece una
vacunación, quién la aplicó y en qué fecha. Y con `prescription.create` se podían
añadir ítems tras el cierre, lo que ensancha el tope que limita la dispensación
(el cap se calcula sobre `PrescriptionItem.quantity`).

La regla NO es «después del cierre no se toca nada»: ambas vistas describen su
documento como retenido legalmente (NOM-007/NOM-046, cinco años) y proponen el
PATCH de la nota como única vía de anulación. Bloquear la mutación entera
eliminaría esa vía. La regla que se impone es la estrecha: se anota, no se
reescribe.
"""
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import PermissionDenied

from apps.medical_records.models import MedicalRecord
from apps.medical_records.policies import (
    POST_CLOSE_EDITABLE_FIELDS,
    assert_post_close_edit_allowed,
)


class _FakeOrg:
    def __init__(self, pk):
        self.pk = pk
        self.id = pk


class _FakeUser:
    def __init__(self, organization_id):
        self.organization_id = organization_id
        self.id = 1
        self.pk = 1


class _FakeRecord:
    """Sustituto del expediente: la policy solo lee organización y estado."""
    Status = MedicalRecord.Status

    def __init__(self, organization_id, status):
        self.organization_id = organization_id
        self.status = status
        self.id = 99
        self.veterinarian_id = None


class PostCloseEditPolicyTests(SimpleTestCase):
    """La policy es pura respecto de la base: se prueba sin DB."""

    def setUp(self):
        self.user = _FakeUser(organization_id=7)

    def _closed(self):
        return _FakeRecord(7, MedicalRecord.Status.CLOSED)

    def _open(self):
        return _FakeRecord(7, MedicalRecord.Status.OPEN)

    def test_open_record_allows_any_field(self):
        assert_post_close_edit_allowed(
            self.user, self._open(),
            changed_fields=['pet', 'applied_by', 'application_date'],
        )

    def test_closed_record_allows_the_annotation(self):
        assert_post_close_edit_allowed(
            self.user, self._closed(), changed_fields=['notes'],
        )

    def test_closed_record_rejects_patient_reassignment(self):
        with self.assertRaises(PermissionDenied):
            assert_post_close_edit_allowed(
                self.user, self._closed(), changed_fields=['pet'],
            )

    def test_closed_record_rejects_authorship_change(self):
        """Falsificar quién aplicó una vacuna es el caso que más importa."""
        with self.assertRaises(PermissionDenied):
            assert_post_close_edit_allowed(
                self.user, self._closed(), changed_fields=['applied_by'],
            )

    def test_closed_record_rejects_date_change(self):
        with self.assertRaises(PermissionDenied):
            assert_post_close_edit_allowed(
                self.user, self._closed(), changed_fields=['application_date'],
            )

    def test_closed_record_rejects_prescription_items_replacement(self):
        """`PrescriptionSerializer.update` reemplaza `items`: también cuenta."""
        with self.assertRaises(PermissionDenied):
            assert_post_close_edit_allowed(
                self.user, self._closed(), changed_fields=['items'],
            )

    def test_closed_record_rejects_a_mix_that_includes_the_annotation(self):
        """Colar un campo prohibido junto a `notes` no lo vuelve admisible."""
        with self.assertRaises(PermissionDenied):
            assert_post_close_edit_allowed(
                self.user, self._closed(), changed_fields=['notes', 'pet'],
            )

    def test_record_of_another_organization_is_refused_regardless_of_status(self):
        foreign = _FakeRecord(8, MedicalRecord.Status.OPEN)
        with self.assertRaises(PermissionDenied):
            assert_post_close_edit_allowed(
                self.user, foreign, changed_fields=['notes'],
            )

    def test_absent_record_does_not_restrict(self):
        """Un registro sin consulta asociada no hereda un cierre inexistente."""
        assert_post_close_edit_allowed(
            self.user, None, changed_fields=['pet', 'applied_by'],
        )

    def test_allowlist_is_only_the_annotation(self):
        """Ancla del contrato: ampliar esta lista es una decisión de producto."""
        self.assertEqual(set(POST_CLOSE_EDITABLE_FIELDS), {'notes'})


class PostCloseGuardWiringTests(TestCase):
    """Gate estático: las vistas que mutan estos hijos invocan el guard.

    La regresión que esto cubre no es un cálculo equivocado sino una OMISIÓN: el
    guard existía y estas vistas no lo llamaban. Un test de comportamiento sobre
    una sola de ellas no impediría que una vista nueva repita el olvido.
    """

    def test_prescription_item_views_call_the_closed_guard(self):
        import inspect

        from apps.prescriptions import views as presc_views

        for view_name in ('PrescriptionItemCreateView', 'PrescriptionItemDeleteView'):
            source = inspect.getsource(getattr(presc_views, view_name))
            self.assertIn(
                'assert_can_modify_medical_record', source,
                f"{view_name} no invoca el guard de cierre: una receta de una "
                f"consulta cerrada volvería a ser mutable.",
            )

    def test_vaccine_serializer_calls_the_post_close_policy(self):
        import inspect

        from apps.medical_records.serializers import VaccineRecordSerializer

        source = inspect.getsource(VaccineRecordSerializer)
        self.assertIn(
            'assert_post_close_edit_allowed', source,
            'VaccineRecordSerializer no aplica la inmutabilidad post-cierre.',
        )

    def test_prescription_serializer_calls_the_post_close_policy(self):
        import inspect

        from apps.prescriptions.serializers import PrescriptionSerializer

        source = inspect.getsource(PrescriptionSerializer)
        self.assertIn(
            'assert_post_close_edit_allowed', source,
            'PrescriptionSerializer no aplica la inmutabilidad post-cierre.',
        )
