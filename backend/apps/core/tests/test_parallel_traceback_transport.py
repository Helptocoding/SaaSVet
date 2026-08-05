"""Gate del transporte de fallos entre procesos (`manage.py test --parallel`).

Regresión que protege: `--parallel` devuelve cada fallo del worker al proceso
padre por `pickle`. Un `TracebackType` de CPython no es picklable; Django solo
lo consigue porque `RemoteTestResult.__init__` llama a
`tblib.pickling_support.install()`. Si `tblib` no está en el entorno, el primer
test que falle revienta a su worker con
`TypeError: cannot pickle 'traceback' object`, multiprocessing re-lanza esa
excepción en el padre y la corrida entera muere sin reportar qué test falló.

Ocurrió 4 veces en un mismo día con la suite completa: cero resultados de ~1500
tests. La dependencia está declarada en `requirements.txt` y pinneada en
`requirements.lock`; lo que faltaba era algo que gritara cuando el entorno no
las tiene. Este archivo es la segunda red (la primera es el guard del runner,
que aborta antes de arrancar el pool): en serie reporta el problema con nombre
y apellido.
"""

import pickle
import sys
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test import runner as django_test_runner
from django.test.runner import RemoteTestResult

from apps.core.test_runner import (
    VetCareTestRunner,
    verificar_transporte_de_tracebacks,
)


def _exc_info_de_un_fallo():
    """Un `sys.exc_info()` real: exactamente lo que Django manda al padre."""
    try:
        raise AssertionError("fallo simulado de un test")
    except AssertionError:
        return sys.exc_info()


class TransporteDeTracebacksTests(SimpleTestCase):
    def test_tblib_disponible_para_el_runner(self):
        self.assertIsNotNone(
            django_test_runner.tblib,
            "Django no ve tblib: con --parallel el primer fallo tumbará la "
            "corrida completa sin decir qué test fue. Sincroniza el entorno "
            "con `pip install -r requirements.lock`.",
        )

    def test_un_fallo_sobrevive_al_viaje_entre_procesos(self):
        # Construir el result es lo que registra el reductor de tracebacks en
        # copyreg; sin esa llamada el pickle de abajo revienta.
        RemoteTestResult()
        err = _exc_info_de_un_fallo()

        tipo, valor, tb = pickle.loads(pickle.dumps(err))

        self.assertIs(tipo, AssertionError)
        self.assertEqual(str(valor), "fallo simulado de un test")
        # El traceback es lo único que se perdía: sin él, el padre no puede
        # decir en qué línea falló el test.
        self.assertIsNotNone(tb)
        self.assertEqual(
            tb.tb_frame.f_code.co_name, "_exc_info_de_un_fallo"
        )


class GuardDelRunnerTests(SimpleTestCase):
    """El guard debe disparar solo cuando hay paralelismo real."""

    def test_aborta_si_falta_tblib_y_se_pidio_paralelo(self):
        with mock.patch.object(django_test_runner, "tblib", None):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                verificar_transporte_de_tracebacks(4)
        # El mensaje es el entregable: quien lo vea debe saber qué hacer.
        self.assertIn("tblib", str(ctx.exception))
        self.assertIn("requirements.lock", str(ctx.exception))

    def test_no_estorba_en_serie_aunque_falte_tblib(self):
        # Sin pool no hay pickle: exigir tblib para correr en serie sería
        # romper a quien solo quiere lanzar un test suelto.
        with mock.patch.object(django_test_runner, "tblib", None):
            verificar_transporte_de_tracebacks(0)
            verificar_transporte_de_tracebacks(1)

    def test_no_aborta_con_tblib_presente(self):
        verificar_transporte_de_tracebacks(4)


class DondeSeEngranaElGuardTests(SimpleTestCase):
    """El guard corre en `build_suite`, no antes. Ese punto es el contrato.

    `build_suite` recorta `self.parallel` a `min(pedido, nº de subsuites)` y
    todavía ocurre antes de `setup_databases()`. Enganchar antes (p.ej. en
    `setup_test_environment`) leería el paralelismo PEDIDO en vez del REAL y
    abortaría corridas que iban a ejecutarse en un solo proceso.
    """

    ESTE_MODULO = "apps.core.tests.test_parallel_traceback_transport"

    def test_aborta_al_construir_la_suite_si_el_paralelismo_es_real(self):
        runner = VetCareTestRunner(parallel=4, verbosity=0)
        with mock.patch.object(django_test_runner, "tblib", None):
            with self.assertRaises(ImproperlyConfigured):
                runner.build_suite([self.ESTE_MODULO])

    def test_una_sola_clase_con_parallel_no_es_paralelismo_real(self):
        # `--parallel auto` sobre una única clase colapsa a 1 proceso: no hay
        # pickle de por medio y abortar sería un falso positivo.
        runner = VetCareTestRunner(parallel=4, verbosity=0)
        with mock.patch.object(django_test_runner, "tblib", None):
            runner.build_suite([f"{self.ESTE_MODULO}.GuardDelRunnerTests"])
        self.assertEqual(runner.parallel, 1)
