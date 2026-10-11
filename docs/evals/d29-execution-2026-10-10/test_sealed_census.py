import unittest
from sealed_census import output_row


class SealedCensusTests(unittest.TestCase):
    def setUp(self):self.census=dict(messages=[dict(id=1,direction='out',status='uncertain',send_admitted_at='2026-10-10 11:00:00.123456-06:00')])
    def test_exact_captured_admission_and_uncertainty(self):
        row=output_row(self.census,pk=1)
        self.assertEqual((row.pk,row.status,row.send_admitted_at.isoformat()),(1,'uncertain','2026-10-10T11:00:00.123456-06:00'))
    def test_missing_or_duplicated_row_rejected(self):
        with self.assertRaises(ValueError):output_row(self.census,pk=2)
        self.census['messages']*=2
        with self.assertRaises(ValueError):output_row(self.census,pk=1)
    def test_missing_timezone_rejected(self):
        self.census['messages'][0]['send_admitted_at']='2026-10-10 11:00:00.123456'
        with self.assertRaises(ValueError):output_row(self.census,pk=1)
