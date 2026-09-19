"""B7A v1 exact definition: pure canonicalization and digest acceptance."""
from datetime import date, time
from django.test import SimpleTestCase
from apps.agent.operation_schema import canonicalize, digest, InvalidParameters


class OperationSchemaTests(SimpleTestCase):
    def params(self):
        return dict(pet_id=1, date='2026-12-18', start_time='10:00',
                    end_time='10:30', veterinarian_id=2, reason='Consulta')

    def test_equivalent_types_and_order(self):
        a = self.params()
        b = dict(reversed(list(a.items())))
        b.update(pet_id='001', date=date(2026, 12, 18), start_time=time(10))
        self.assertEqual(canonicalize('CREATE_APPOINTMENT', a), canonicalize('CREATE_APPOINTMENT', b))
        self.assertEqual(digest('CREATE_APPOINTMENT', a), digest('CREATE_APPOINTMENT', b))
        for value in ('9:00', '9:00:00', '09:00:00', time(9)):
            self.assertEqual(canonicalize('CREATE_APPOINTMENT', {**a, 'start_time': value})['start_time'], '09:00')

    def test_every_sensitive_parameter_changes_digest(self):
        a = self.params()
        for field, value in dict(pet_id=3, date='2026-12-19', start_time='10:01',
                                 end_time='11:00', veterinarian_id=4, reason='Vacunación').items():
            with self.subTest(field=field):
                self.assertNotEqual(digest('CREATE_APPOINTMENT', a),
                                    digest('CREATE_APPOINTMENT', {**a, field: value}))

    def test_h01_appointment_and_action_are_distinct(self):
        a = {'appointment_id': 1}
        self.assertNotEqual(digest('CANCEL_APPOINTMENT', a),
                            digest('CANCEL_APPOINTMENT', {'appointment_id': 2}))
        self.assertNotEqual(digest('CANCEL_APPOINTMENT', a),
                            digest('CONFIRM_ATTENDANCE', {**a, 'target_status': 'confirmed'}))

    def test_reject_unknown_keys_types_versions_and_kinds(self):
        cases = [dict(pet_id=True), dict(start_time='10:00:01'), dict(reason=None),
                 dict(operation_key='untrusted'), dict(service_id=2), dict(end_time='09:00')]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(InvalidParameters):
                canonicalize('CREATE_APPOINTMENT', {**self.params(), **change})
        for kind, version in [('PAYMENT', 1), ('CREATE_APPOINTMENT', 2)]:
            with self.assertRaises(InvalidParameters):
                canonicalize(kind, self.params(), version=version)

    def test_optional_empty_has_one_meaning_but_null_is_rejected(self):
        self.assertEqual(canonicalize('CANCEL_APPOINTMENT', {'appointment_id': 1}),
                         canonicalize('CANCEL_APPOINTMENT', {'appointment_id': '1', 'cancellation_reason': ''}))
        with self.assertRaises(InvalidParameters):
            canonicalize('CANCEL_APPOINTMENT', {'appointment_id': 1, 'cancellation_reason': None})

    def test_register_pet_supported_fields_only(self):
        self.assertEqual(canonicalize('REGISTER_PET', {'owner_id': '1', 'name': '  Luna  ', 'species': 'canino'}),
                         {'owner_id': 1, 'name': 'Luna', 'species': 'canino'})
        with self.assertRaises(InvalidParameters):
            canonicalize('REGISTER_PET', {'owner_id': 1, 'name': 'Luna', 'medical_notes': 'private'})
