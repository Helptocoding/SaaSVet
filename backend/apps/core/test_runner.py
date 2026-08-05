"""Runner de tests del proyecto.

Existe por un único motivo: que `manage.py test --parallel` no pueda volver a
perder la corrida entera sin decir qué test falló.

Cómo se pierde: `--parallel` reparte los tests entre procesos y devuelve los
fallos al padre por `pickle`. Un traceback de CPython NO es picklable; Django
solo lo consigue si `tblib` está instalado (`RemoteTestResult.__init__` llama a
`tblib.pickling_support.install()`, que registra el reductor en `copyreg`). Sin
tblib, el PRIMER test que falla revienta a su worker con
`TypeError: cannot pickle 'traceback' object` dentro de `_confirm_picklable`,
multiprocessing re-lanza esa excepción en el proceso padre y la corrida muere
ahí: ~1500 tests sin resultado y ni el nombre del que falló. Django avisa por
stdout del worker, pero ese aviso queda sepultado entre miles de líneas y a
menudo se imprime DESPUÉS del traceback fatal.

tblib ya está declarado en `requirements.txt` y pinneado en `requirements.lock`,
así que en un entorno sincronizado esto no ocurre. El agujero es el entorno
desincronizado (o un lock regenerado sin la dependencia): la ausencia es
silenciosa hasta que alguien rompe un test, y para entonces el coste es una
corrida completa. Aquí se convierte ese silencio en un error explícito ANTES de
crear las bases de datos de test y de arrancar el pool de procesos.

Este runner NO toca el transporte de resultados de Django (no serializa
tracebacks como texto ni reimplementa `RemoteTestResult`): solo valida una
precondición y delega todo lo demás en `DiscoverRunner`.
"""

from django.core.exceptions import ImproperlyConfigured
from django.test import runner as django_test_runner
from django.test.runner import DiscoverRunner

MENSAJE_SIN_TBLIB = (
    "Falta la dependencia 'tblib' y se pidió --parallel.\n"
    "\n"
    "Sin tblib los tracebacks no son serializables entre procesos: el primer "
    "test que falle abortará la corrida completa con "
    "\"TypeError: cannot pickle 'traceback' object\" y sin indicar qué test "
    "falló.\n"
    "\n"
    "Solución (tblib ya está pinneado en el lockfile):\n"
    "    pip install -r requirements.lock\n"
    "\n"
    "Alternativa puntual: correr en serie con --parallel 1 (más lento, pero "
    "reporta los fallos correctamente)."
)


def verificar_transporte_de_tracebacks(parallel):
    """Aborta si se pidió paralelismo real y los tracebacks no viajarán.

    Se separa del runner para poder ejercitarla en un test sin montar toda la
    maquinaria de `DiscoverRunner`.
    """
    # `parallel` es 0 en modo serie y 1 cuando se pidió explícitamente un solo
    # proceso: en ambos casos no hay pickle de por medio y tblib es irrelevante.
    if parallel <= 1:
        return
    if django_test_runner.tblib is None:
        raise ImproperlyConfigured(MENSAJE_SIN_TBLIB)


class VetCareTestRunner(DiscoverRunner):
    """`DiscoverRunner` + la verificación de arriba, nada más."""

    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        # DESPUÉS de `super()` y ANTES de `setup_databases()`, que es justo la
        # ventana donde `self.parallel` ya es el paralelismo REAL y todavía no
        # se creó ninguna base de datos.
        #
        # Importa que sea después: `build_suite` recorta `self.parallel` a
        # `min(pedido, nº de subsuites)`. Pedir `--parallel auto` sobre una sola
        # clase de tests colapsa a 1 proceso, no hay pickle de por medio y
        # abortar ahí sería un falso positivo.
        verificar_transporte_de_tracebacks(self.parallel)
        return suite
