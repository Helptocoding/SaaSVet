"""Historical cross-endpoint concurrency coverage, adapted to current APIs."""
import threading
import traceback
from datetime import timedelta
from unittest import mock

from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.patients.models import Owner, Pet
from .test_no_overlap import _seed, _slot


class CrossPathCreationRacesTests(TransactionTestCase):
    """Carreras entre vías de creación DISTINTAS por el mismo hueco.

    Las 500 carreras de `RepeatedConcurrentCreationTests` enfrentan dos `POST`
    normales. Estas enfrentan vías distintas, que es donde un lock olvidado en
    una sola de ellas dejaría de serializar: `POST` contra
    `create-with-patient` y `POST` contra atención sin cita.

    Exigencia en las tres: cero 500, cero escrituras parciales y un desenlace
    de negocio definido.
    """

    BARRIER_TIMEOUT = 30
    JOIN_TIMEOUT = 60

    def setUp(self):
        self.org, self.admin, self.vet, self.pet_a, self.pet_b = _seed(
            "INV-D vías cruzadas", "cross")

    def tearDown(self):
        connections.close_all()

    def _race(self, fn_a, fn_b):
        barrier = threading.Barrier(2)
        outcomes = {}

        def runner(name, fn):
            try:
                client = APIClient()
                client.force_authenticate(self.admin)
                barrier.wait(timeout=self.BARRIER_TIMEOUT)
                outcomes[name] = ('ok', fn(client))
            except BaseException:  # noqa: BLE001
                barrier.abort()
                outcomes[name] = ('error', traceback.format_exc())
            finally:
                connections.close_all()

        threads = {n: threading.Thread(target=runner, args=(n, f), name=f"cross-{n}")
                   for n, f in (("a", fn_a), ("b", fn_b))}
        for t in threads.values():
            t.start()
        for name, t in threads.items():
            t.join(timeout=self.JOIN_TIMEOUT)
            self.assertFalse(t.is_alive(), f"hilo {name} colgado")

        crashed = {n: tb for n, (kind, tb) in outcomes.items() if kind == 'error'}
        if crashed:
            detail = "\n\n".join(f"--- hilo {n} ---\n{tb}" for n, tb in crashed.items())
            self.fail(f"Un hilo murió en vez de responder:\n\n{detail}")
        return {n: v for n, (_, v) in outcomes.items()}

    def _assert_business_outcome(self, results, expected_active):
        self.assertEqual(set(results), {'a', 'b'})
        codes = [c for c, _ in results.values()]
        self.assertCountEqual(codes, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST], results)
        self.assertNotIn(
            status.HTTP_500_INTERNAL_SERVER_ERROR, codes,
            f"una vía terminó en 500: {results}")
        for code, body in results.values():
            if code >= 400:
                self.assertEqual(body.get("code"), "slot_taken", body)
        active = Appointment.objects.filter(
            organization=self.org, veterinarian=self.vet,
            status__in=('scheduled', 'confirmed', 'in_progress'),
        ).count()
        self.assertEqual(active, expected_active, results)

    def test_post_versus_create_with_patient(self):
        date, start, end = _slot(days=3, hour=10)
        owners_before = Owner.objects.filter(organization=self.org).count()
        pets_before = Pet.objects.filter(organization=self.org).count()

        def plain(client):
            r = client.post("/api/appointments/", {
                "pet": self.pet_a.id, "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "x",
            })
            return r.status_code, r.json()

        def with_patient(client):
            r = client.post("/api/appointments/create-with-patient/", {
                "owner_name": "Cliente Carrera", "owner_phone": "5511119999",
                "pet_name": "Nube", "pet_species": "felino",
                "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "y",
            })
            return r.status_code, r.json()

        results = self._race(plain, with_patient)
        self._assert_business_outcome(results, expected_active=1)

        # Cero escrituras parciales: si `create-with-patient` perdió el cupo,
        # su Owner y su Pet se deshicieron con la transacción.
        cwp_code = results['b'][0]
        if cwp_code >= 400:
            self.assertEqual(
                Owner.objects.filter(organization=self.org).count(), owners_before)
            self.assertEqual(
                Pet.objects.filter(organization=self.org).count(), pets_before)

    def test_post_versus_walk_in(self):
        """El `POST` apunta a un hueco que solapa la atención sin cita.

        La atención sin cita ocupa `[ahora, ahora+30min)`. El `POST` va a
        `[ahora+10, ahora+25)`: solapa, pero es futuro — a la hora exacta de
        «ahora» chocaría antes con el guard de fecha pasada y la carrera no
        llegaría a disputarse el cupo.
        """
        now_local = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        post_start = now_local + timedelta(minutes=10)
        post_end = now_local + timedelta(minutes=25)
        date = now_local.date().isoformat()
        start = post_start.time().replace(second=0, microsecond=0).strftime("%H:%M")
        end = post_end.time().replace(second=0, microsecond=0).strftime("%H:%M")

        def plain(client):
            r = client.post("/api/appointments/", {
                "pet": self.pet_a.id, "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "x",
            })
            return r.status_code, r.json()

        def walk_in(client):
            r = client.post("/api/appointments/walk-in/", {
                "pet": self.pet_b.id, "veterinarian": self.vet.id,
                "reason": "urgencia",
            })
            return r.status_code, r.json()

        with mock.patch('django.utils.timezone.now', return_value=now_local):
            results = self._race(plain, walk_in)
        self._assert_business_outcome(results, expected_active=1)
