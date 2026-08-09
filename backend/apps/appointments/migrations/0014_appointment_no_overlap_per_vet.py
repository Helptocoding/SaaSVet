"""INV-D — un veterinario no tiene dos citas activas solapadas (ADR p57 §3.4).

Migración ESTRUCTURAL y no reversible en caliente. PostgreSQL **no** admite
añadir una restricción de exclusión `NOT VALID`: cubre todas las filas activas
desde el instante en que se aplica, así que **falla si hay solapes históricos**.
Eso es lo correcto (fail-closed), y por eso la secuencia de deploy es:

  1. `python manage.py audit_appointment_overlaps`  (en CADA entorno, incluida
     producción) — lista los pares solapados por organización con su public_id.
  2. **Remediación humana** por clínica de lo que reporte. No se corrige solo:
     cancelar o mover una cita real sin que nadie lo decida es peor que el
     solape.
  3. Aplicar esta migración en ventana de deploy — construir el índice GiST
     toma un lock fuerte de la tabla (segundos con el volumen del piloto).
  4. Volver a correr la auditoría post-deploy.

Correr la auditoría el MISMO día del deploy, no una semana antes: una cita
creada en medio hace fallar la migración.

`btree_gist` es requisito, no adorno: los componentes de igualdad
(organization, veterinarian) no son indexables por GiST sin esa extensión.
Precedente en el proyecto: `TrigramExtension` en `patients/0012`.
"""
import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models

import apps.appointments.models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0013_appointment_idempotency_key_and_more'),
    ]

    operations = [
        BtreeGistExtension(),
        migrations.AddConstraint(
            model_name='appointment',
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=(
                    models.Q(status__in=['scheduled', 'confirmed', 'in_progress'])
                    & models.Q(veterinarian__isnull=False)
                    & models.Q(start_datetime__isnull=False)
                    & models.Q(end_datetime__isnull=False)
                ),
                expressions=[
                    ('organization', '='),
                    ('veterinarian', '='),
                    (
                        apps.appointments.models.TsTzRange(
                            'start_datetime',
                            'end_datetime',
                            django.contrib.postgres.fields.ranges.RangeBoundary(),
                        ),
                        '&&',
                    ),
                ],
                name='appointment_no_overlap_per_vet',
            ),
        ),
    ]
