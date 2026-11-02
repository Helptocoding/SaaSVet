"""Gate: todo setting leído con `getattr(settings, 'NOMBRE', ...)` debe existir.

Origen (auditoría de seguridad run-1, hallazgo
`channels/crypto/agent-token-enc-key-setting-never-defined`):

`apps/channels/crypto.py` elegía la clave de cifrado de secretos en reposo con

    key = getattr(settings, 'AGENT_TOKEN_ENC_KEY', '') or ''

y `config/settings.py` **nunca definía ese nombre**. En este proyecto la única
vía para promover una variable de entorno a settings es `config()` de
`decouple`, así que el `getattr` devolvía siempre el default: la rama de clave
dedicada era código muerto, la clave se derivaba siempre de `SECRET_KEY`, y un
operador que pusiera `AGENT_TOKEN_ENC_KEY` en `.env.prod` no obtenía efecto
alguno ni aviso alguno. Un control de seguridad documentado que no existía.

La misma auditoría encontró dos instancias más del patrón
(`AGENT_LLM_MAX_RETRIES`, `AGENT_LLM_RETRY_DELAY_SECONDS`), lo que confirma que
no era un caso aislado sino una CLASE: `getattr` con default nunca falla, así
que el olvido es invisible para siempre.

Este gate es de **tolerancia cero y sin baseline**, igual que
`test_calendar_rule_audit.py`. Si añades un `getattr(settings, 'X', ...)`,
define `X` en `config/settings.py` — normalmente con `config('X', default=...)`
para que el entorno pueda ajustarlo de verdad.

Dos escapes legítimos, ambos deliberados:

* `getattr(settings, VARIABLE, ...)` con nombre no literal: no es resoluble
  estáticamente y se ignora.
* Un setting de Django/terceros (p. ej. `DEBUG`, `CORS_EXPOSE_HEADERS`) cuenta
  como definido, porque `hasattr` lo ve igual. Eso es correcto: lo que el gate
  prohíbe es leer un nombre que NADIE define.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APPS_DIR = Path(settings.BASE_DIR) / 'apps'

# getattr(settings, 'NOMBRE'  — solo nombres literales en MAYÚSCULAS.
# Acepta ambas comillas y espacios arbitrarios, incluido salto de línea entre
# argumentos, que es como está escrito en varios call sites del repo.
_GETATTR_SETTING = re.compile(
    r"""getattr\(\s*settings\s*,\s*['"]([A-Z_][A-Z0-9_]*)['"]""",
    re.VERBOSE,
)


def _iter_source_files():
    """Código de producción: excluye tests y migraciones."""
    for path in APPS_DIR.rglob('*.py'):
        parts = path.parts
        if 'tests' in parts or 'migrations' in parts:
            continue
        yield path


class SettingsGetattrContractTests(SimpleTestCase):

    def test_every_getattr_setting_is_defined(self):
        missing = {}
        for path in _iter_source_files():
            text = path.read_text(encoding='utf-8', errors='replace')
            for name in _GETATTR_SETTING.findall(text):
                if not hasattr(settings, name):
                    rel = path.relative_to(Path(settings.BASE_DIR))
                    missing.setdefault(name, set()).add(str(rel).replace('\\', '/'))

        if missing:
            detail = '\n'.join(
                f"  - {name}: leído en {', '.join(sorted(files))}"
                for name, files in sorted(missing.items())
            )
            self.fail(
                "Settings leídos con getattr() pero NO definidos en "
                "config/settings.py:\n"
                f"{detail}\n\n"
                "getattr() con default nunca falla, así que la rama que depende "
                "de este setting es código muerto y la variable de entorno "
                "correspondiente no tiene ningún efecto. Defínelo en "
                "config/settings.py, normalmente como "
                "config('NOMBRE', default=<el mismo default del getattr>)."
            )

    def test_gate_detects_an_undefined_setting(self):
        """El gate sirve de algo: un nombre inventado debe considerarse ausente.

        Sin esto, un fallo del regex o de la recolección dejaría el test en
        verde para siempre sin comprobar nada.
        """
        self.assertFalse(
            hasattr(settings, 'DEFINITELY_NOT_A_REAL_SETTING_XYZ'),
            "El centinela existe como setting — renómbralo.",
        )
        sample = "value = getattr(settings, 'DEFINITELY_NOT_A_REAL_SETTING_XYZ', '')"
        found = _GETATTR_SETTING.findall(sample)
        self.assertEqual(found, ['DEFINITELY_NOT_A_REAL_SETTING_XYZ'])

    def test_regression_agent_token_enc_key_is_defined(self):
        """Ancla del hallazgo concreto que originó el gate."""
        self.assertTrue(
            hasattr(settings, 'AGENT_TOKEN_ENC_KEY'),
            "AGENT_TOKEN_ENC_KEY volvió a quedar sin definir: la separación de "
            "clave para secretos en reposo es inalcanzable otra vez y la clave "
            "se deriva siempre de SECRET_KEY.",
        )
