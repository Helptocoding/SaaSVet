"""Separación de clave para secretos en reposo (auditoría run-1, hallazgo
`channels/crypto/agent-token-enc-key-setting-never-defined`).

`_fernet()` prefiere `settings.AGENT_TOKEN_ENC_KEY` y solo deriva de
`SECRET_KEY` cuando ese override está vacío. La lógica siempre fue correcta;
lo que faltaba era la línea en `config/settings.py` que promueve la variable de
entorno, así que el `getattr` devolvía siempre `''` y la rama dedicada era
código muerto en TODO despliegue.

Lo que protege esta separación, y por qué importa el orden de rotación:

* rotar `SECRET_KEY` —la respuesta estándar ante sospecha de fuga— NO debe
  dejar indescifrables los access tokens del proveedor ya guardados en DB;
* una fuga de `SECRET_KEY` NO debe además descifrarlos.

Sin el override, ambas cosas fallaban a la vez y en silencio.

El gate `apps/core/tests/test_settings_getattr_contract.py` cubre la clase
general (cualquier setting leído con getattr y nunca definido). Este archivo
prueba el comportamiento concreto del cifrado.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.test import SimpleTestCase, override_settings

from apps.channels.crypto import decrypt_secret, encrypt_secret

# Clave dedicada fija: el test no debe depender de una generada al azar para
# poder afirmar que el ciphertext NO lo descifra la derivada de SECRET_KEY.
DEDICATED_KEY = Fernet.generate_key().decode()


def _secret_key_derived_fernet(secret_key):
    """Reproduce la derivación del fallback, para probar que NO sirve."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class FernetKeySelectionTests(SimpleTestCase):

    @override_settings(AGENT_TOKEN_ENC_KEY=DEDICATED_KEY)
    def test_uses_dedicated_key_when_configured(self):
        token = encrypt_secret('EAAG-provider-token')
        self.assertEqual(decrypt_secret(token), 'EAAG-provider-token')
        # Y lo descifra la clave dedicada, no otra.
        self.assertEqual(
            Fernet(DEDICATED_KEY.encode()).decrypt(token.encode()).decode(),
            'EAAG-provider-token',
        )

    @override_settings(AGENT_TOKEN_ENC_KEY=DEDICATED_KEY, SECRET_KEY='clave-de-firma-distinta')
    def test_secret_key_cannot_decrypt_when_dedicated_key_is_set(self):
        """El corazón del hallazgo: con override, SECRET_KEY no abre el secreto.

        Si este test se pone rojo, la separación de claves volvió a no existir y
        una fuga de SECRET_KEY descifra los tokens del proveedor.
        """
        token = encrypt_secret('EAAG-provider-token')
        with self.assertRaises(InvalidToken):
            _secret_key_derived_fernet('clave-de-firma-distinta').decrypt(token.encode())

    @override_settings(AGENT_TOKEN_ENC_KEY='', SECRET_KEY='clave-de-firma-fallback')
    def test_falls_back_to_secret_key_derivation_when_unset(self):
        """Modo degradado: se conserva por compatibilidad con lo ya guardado."""
        token = encrypt_secret('EAAG-provider-token')
        self.assertEqual(
            _secret_key_derived_fernet('clave-de-firma-fallback')
            .decrypt(token.encode()).decode(),
            'EAAG-provider-token',
        )

    @override_settings(AGENT_TOKEN_ENC_KEY=DEDICATED_KEY)
    def test_rotating_secret_key_does_not_break_stored_secrets(self):
        """La consecuencia operativa que justifica el arreglo.

        Se cifra con una SECRET_KEY y se descifra tras rotarla. Con el fallback
        activo esto fallaría, que es exactamente lo que rompería el envío
        saliente en medio de un incidente de rotación.
        """
        with override_settings(SECRET_KEY='antes-de-rotar'):
            token = encrypt_secret('EAAG-provider-token')
        with override_settings(SECRET_KEY='despues-de-rotar'):
            self.assertEqual(decrypt_secret(token), 'EAAG-provider-token')

    @override_settings(AGENT_TOKEN_ENC_KEY='')
    def test_rotating_secret_key_breaks_stored_secrets_in_degraded_mode(self):
        """Contraparte honesta: sin override, rotar SÍ invalida lo guardado.

        Documenta el riesgo que el modo degradado conserva, para que el aviso
        [SEC] del arranque no parezca decorativo.
        """
        with override_settings(SECRET_KEY='antes-de-rotar'):
            token = encrypt_secret('EAAG-provider-token')
        with override_settings(SECRET_KEY='despues-de-rotar'):
            self.assertEqual(decrypt_secret(token), '')
