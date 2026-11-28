"""Catálogo cerrado de zonas horarias de México (ADR p70 D1).

La zona se elige de esta lista, con nombre para personas; no se escribe a mano.
El frontend tiene una copia en ``frontend/src/features/config/timezones.json`` y
una prueba exige que coincidan. Los identificadores son IANA (se guardan en
``Organization.timezone``); las etiquetas son lo que se muestra.

El orden es el de presentación: primero la zona Centro, la más común.
"""
MEXICO_TIMEZONES = (
    ('America/Mexico_City', 'Centro — Ciudad de México'),
    ('America/Monterrey', 'Centro — Monterrey'),
    ('America/Merida', 'Centro — Mérida'),
    ('America/Chihuahua', 'Centro — Chihuahua'),
    ('America/Bahia_Banderas', 'Centro — Bahía de Banderas'),
    ('America/Cancun', 'Sureste — Cancún (Quintana Roo)'),
    ('America/Mazatlan', 'Pacífico — Mazatlán'),
    ('America/Hermosillo', 'Pacífico — Hermosillo (Sonora)'),
    ('America/Tijuana', 'Noroeste — Tijuana (Baja California)'),
    ('America/Ciudad_Juarez', 'Frontera norte — Ciudad Juárez'),
    ('America/Ojinaga', 'Frontera norte — Ojinaga'),
    ('America/Matamoros', 'Frontera norte — Matamoros'),
)

TIMEZONE_CODES = frozenset(code for code, _ in MEXICO_TIMEZONES)
DEFAULT_TIMEZONE = 'America/Mexico_City'
