"""INV-C (ADR p57 / decisión §4.7.2, §4.8, §4.12) — clave de identidad por teléfono.

Migración **aditiva y derivada**:
  · columna `phone_normalized` + índice `(organization, phone_normalized)`;
  · backfill por lotes a partir del `phone` existente.

Lo que esta migración NO hace, y no es un olvido:

  · **No toca `phone`.** El texto que tecleó cada clínica se conserva.
  · **No añade restricción única.** INV-C admite duplicados históricos y obliga
    a tratarlos como `owner_ambiguous`; una `UNIQUE` exigiría fusionarlos, que
    es exactamente lo prohibido (§4.7.1).
  · **No fusiona ni borra nada.** Los duplicados se listan con
    `audit_owner_phone_duplicates` y los ordena una persona.

Es recalculable: si el backfill saliera mal, se vuelve a derivar del `phone`.
"""
from django.db import migrations, models

# Lotes por ventana de PK. La tabla `Owner` de una clínica importada ronda los
# miles de filas; el lote acota la duración del UPDATE y su footprint de WAL.
_BATCH = 5000


def _backfill(apps, schema_editor):
    """Deriva la clave de las filas existentes.

    Regla idéntica a `core.validators.phone_key` + §4.12, expresada en SQL para
    no arrastrar N+1 sobre toda la tabla:
      · solo dígitos; exactamente 10 → clave, si no queda NULL;
      · `is_generic=True` → **NULL siempre**, sin pasar por la normalización.
        Si el genérico normalizara su relleno `'0000000000'`, entraría en la
        deduplicación de todas las organizaciones a la vez (P0-28).
    """
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        raise RuntimeError(
            'El backfill de phone_normalized exige PostgreSQL: la derivación '
            'usa regexp_replace y el proyecto es PostgreSQL-only.'
        )

    with connection.cursor() as cur:
        cur.execute('SELECT COALESCE(MIN(id), 0), COALESCE(MAX(id), 0) FROM patients_owner')
        low, high = cur.fetchone()
        start = low - 1
        while start < high:
            end = start + _BATCH
            cur.execute(
                """
                UPDATE patients_owner AS o
                   SET phone_normalized = d.digits
                  FROM (
                        SELECT id, regexp_replace(phone, '\\D', '', 'g') AS digits
                          FROM patients_owner
                         WHERE id > %s AND id <= %s
                       ) AS d
                 WHERE o.id = d.id
                   AND o.is_generic = false
                   AND length(d.digits) = 10
                """,
                [start, end],
            )
            start = end


def _unbackfill(apps, schema_editor):
    """Sin operación: la columna se elimina al revertir el AddField."""


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0017_owner_owner_phone_trgm_owner_owner_legacy_trgm_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='owner',
            name='phone_normalized',
            field=models.CharField(blank=True, editable=False, max_length=10, null=True),
        ),
        migrations.AddIndex(
            model_name='owner',
            index=models.Index(
                fields=['organization', 'phone_normalized'],
                name='owner_phone_key_idx',
            ),
        ),
        migrations.RunPython(_backfill, _unbackfill),
    ]
