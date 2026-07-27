"""Validadores compartidos de dominio.

Dueño ÚNICO de la regla de teléfono mexicano. Antes vivía duplicada e
inconsistente: `OwnerSerializer` exigía 10 dígitos mientras que
`OrganizationSerializer` solo quitaba los no-dígitos y guardaba lo que quedara
(`"5"` se guardaba como `"5"`; `"no sé"` se guardaba como `""` en silencio).

México-only, misma decisión Q5 que `agent.services.normalize_wa_id`: el dominio
NO migra a E.164 mientras el producto sea MX-only.
"""
import re

from rest_framework import serializers

PHONE_DIGITS = 10

_ONLY_DIGITS = re.compile(r"\D")

PHONE_LENGTH_ERROR = "El teléfono debe tener exactamente 10 dígitos."
PHONE_FILLER_ERROR = (
    "Ese número no parece real. Captura el teléfono al que te pueden llamar."
)


def phone_digits(value):
    """Solo los dígitos de `value` ('' si no hay ninguno o si value es None)."""
    return _ONLY_DIGITS.sub("", value or "")


def is_filler_phone(digits):
    """¿Relleno evidente? (10 dígitos ya normalizados).

    Cubre lo que un usuario teclea para "salir del paso":
      - todos los dígitos iguales  → 1111111111, 0000000000
      - secuencia trivial          → 1234567890, 0123456789, 9876543210

    El paso se compara **módulo 10** porque la secuencia más tecleada de todas
    (`1234567890`) da la vuelta en `9 → 0`: sin el módulo, ese salto vale −9 y
    el número pasaba el filtro.

    Solo existen 20 números de 10 dígitos con paso constante ±1 (uno por dígito
    inicial y sentido), así que el check no puede rechazar un teléfono mexicano
    real: uno de verdad repite algún dígito consecutivo o rompe la progresión.
    """
    if len(digits) != PHONE_DIGITS:
        return False
    if len(set(digits)) == 1:
        return True
    steps = {(int(b) - int(a)) % 10 for a, b in zip(digits, digits[1:])}
    return steps in ({1}, {9})  # 9 == −1 mod 10 (descendente)


def is_valid_mx_phone(value):
    """Predicado sin excepciones: ¿`value` es un teléfono MX utilizable?

    Para callers que DECIDEN en vez de validar entrada (gate del kill switch del
    agente). Cubre también las filas guardadas ANTES de que el serializer
    validara (un `"5"` histórico no pasa).
    """
    digits = phone_digits(value)
    return len(digits) == PHONE_DIGITS and not is_filler_phone(digits)


def validate_mx_phone(value, *, allow_blank=False):
    """Normaliza y valida un teléfono MX. Devuelve los 10 dígitos.

    `allow_blank=True` acepta un valor VACÍO (None / '') y lo devuelve como ''
    — "todavía no capturado". Lo que NUNCA pasa es un valor no vacío que no
    normaliza a un teléfono válido: `"no sé"` es un error explícito, no un
    guardado silencioso en blanco. Esa distinción es la que hace que, arriba,
    *existir* equivalga a *ser válido*.

    Lanza `serializers.ValidationError` — se consume desde serializers DRF.
    """
    if value is None or not str(value).strip():
        if allow_blank:
            return ""
        raise serializers.ValidationError(PHONE_LENGTH_ERROR)

    digits = phone_digits(value)
    if len(digits) != PHONE_DIGITS:
        raise serializers.ValidationError(PHONE_LENGTH_ERROR)
    if is_filler_phone(digits):
        raise serializers.ValidationError(PHONE_FILLER_ERROR)
    return digits
