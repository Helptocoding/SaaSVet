"""
audit_appointment_overlaps — pares de citas ACTIVAS solapadas por veterinario.

INV-D (ADR p57, decisión §3.4). Tiene dos vidas:

  1. **Pre-migración (obligatoria).** `appointments/0014` añade una restricción
     de exclusión y PostgreSQL no admite exclusiones `NOT VALID`: si queda un
     solape histórico, la migración FALLA. Este comando dice exactamente cuáles
     son, por organización y con `public_id`, para que **una persona** de cada
     clínica decida qué hacer (mover, cancelar o desasignar veterinario).
     Nunca corrige nada: cancelar o mover una cita real sin que nadie lo decida
     es peor que el solape.

  2. **Red de seguridad permanente**, igual que `audit_stock_integrity`. Si
     alguna vez apareciera un solape con la restricción activa, significaría que
     la restricción se cayó (migración revertida, restore parcial) — y eso hay
     que verlo desde el cron, no desde el mostrador.

Criterio de solape (idéntico al de la restricción y al pre-chequeo del
serializer): misma organización, mismo veterinario, ambos en estado activo
(`scheduled`, `confirmed`, `in_progress`), con intervalos
`[start_datetime, end_datetime)` que se cruzan. Una cita de 10:00–10:30 y otra
de 10:30–11:00 NO se solapan.

Exit codes (patrón `audit_stock_integrity`, apto para cron):
  0  sin solapes
  1  solapes detectados
  2  error interno
"""
import json
import sys

from django.core.management.base import BaseCommand
from django.db import connection

SAMPLE_SIZE = 50

ACTIVE_STATUSES = ('scheduled', 'confirmed', 'in_progress')

# Auto-join sobre la propia tabla. `a.id < b.id` reporta cada par UNA vez.
# Se hace en SQL y no en Python porque el par es una relación entre filas: el
# ORM obligaría a traer la tabla entera para cruzarla en memoria.
#
# NO se filtra `is_active` — y es deliberado, no un olvido. `Appointment.objects`
# excluye los soft-deleted (`TenantManager`), pero una restricción de la BASE no
# sabe nada de soft delete: cubre TODAS las filas de la tabla. Si esta consulta
# filtrara como el ORM, podría reportar «limpio» y la migración 0014 fallar
# igualmente por un par soft-deleted. El gate tiene que mirar exactamente lo
# mismo que mira PostgreSQL.
#
# Consecuencia derivada (hoy inalcanzable, anotada para que no sorprenda): una
# cita soft-deleted en estado activo seguiría ocupando el hueco a ojos de la
# restricción mientras es invisible para el ORM y para el pre-chequeo → un
# `slot_taken` sin cita visible que lo explique. Hoy nada soft-deletea citas
# (`Appointment` no está registrado en el admin y cancelar usa `status`), así
# que no hay caso vivo. Si alguna vez lo hubiera, la salida de este comando es
# lo que lo hace visible.
_OVERLAP_SQL = """
    SELECT
        a.organization_id,
        a.veterinarian_id,
        a.id            AS a_id,
        a.public_id     AS a_public_id,
        a.status        AS a_status,
        a.start_datetime AS a_start,
        a.end_datetime   AS a_end,
        b.id            AS b_id,
        b.public_id     AS b_public_id,
        b.status        AS b_status,
        b.start_datetime AS b_start,
        b.end_datetime   AS b_end
    FROM appointments_appointment a
    JOIN appointments_appointment b
      ON  a.organization_id = b.organization_id
      AND a.veterinarian_id = b.veterinarian_id
      AND a.id < b.id
      AND a.start_datetime < b.end_datetime
      AND a.end_datetime   > b.start_datetime
    WHERE a.status = ANY(%(statuses)s)
      AND b.status = ANY(%(statuses)s)
      AND a.veterinarian_id IS NOT NULL
      AND a.start_datetime IS NOT NULL AND a.end_datetime IS NOT NULL
      AND b.start_datetime IS NOT NULL AND b.end_datetime IS NOT NULL
      {org_filter}
    ORDER BY a.organization_id, a.veterinarian_id, a.start_datetime, a.id
"""


class Command(BaseCommand):
    help = (
        "Detecta pares de citas activas solapadas por veterinario (INV-D). "
        "Diagnóstico: NO corrige ni cancela nada."
    )

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None,
                            help="Restringe a una organizacion id.")
        parser.add_argument('--json', action='store_true',
                            help="Emite un unico objeto JSON en vez de salida humana.")

    def handle(self, *args, **options):
        try:
            report = self._collect(options['org'])
        except Exception as exc:  # pragma: no cover - defensivo (exit 2)
            self.stderr.write(self.style.ERROR(f"Error interno: {exc}"))
            sys.exit(2)

        if options['json']:
            self.stdout.write(json.dumps(report, default=str, indent=2))
        else:
            self._print_human(report)

        sys.exit(report['exit_code'])

    def _collect(self, org_id):
        org_filter = "AND a.organization_id = %(org)s" if org_id else ""
        params = {'statuses': list(ACTIVE_STATUSES)}
        if org_id:
            params['org'] = org_id

        with connection.cursor() as cursor:
            cursor.execute(_OVERLAP_SQL.format(org_filter=org_filter), params)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        by_org = {}
        for row in rows:
            by_org.setdefault(row['organization_id'], 0)
            by_org[row['organization_id']] += 1

        return {
            'overlap_pairs': len(rows),
            'organizations_affected': sorted(by_org),
            'pairs_by_organization': by_org,
            # El sample lleva public_id porque es lo que el staff puede buscar
            # en la agenda. Sin nombres: el reporte va a logs de ops (sin PII).
            'sample': [
                {
                    'organization_id': r['organization_id'],
                    'veterinarian_id': r['veterinarian_id'],
                    'a': {
                        'public_id': str(r['a_public_id']),
                        'status': r['a_status'],
                        'start': r['a_start'],
                        'end': r['a_end'],
                    },
                    'b': {
                        'public_id': str(r['b_public_id']),
                        'status': r['b_status'],
                        'start': r['b_start'],
                        'end': r['b_end'],
                    },
                }
                for r in rows[:SAMPLE_SIZE]
            ],
            'sample_truncated': len(rows) > SAMPLE_SIZE,
            'exit_code': 1 if rows else 0,
        }

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Auditoria de solapes de agenda (INV-D, ADR p57)"
        ))
        self.stdout.write("")

        if report['overlap_pairs'] == 0:
            self.stdout.write(self.style.SUCCESS(
                "  OK Sin citas activas solapadas. La migracion 0014 puede aplicarse."
            ))
            return

        self.stdout.write(self.style.ERROR(
            f"  X {report['overlap_pairs']} par(es) de citas activas solapadas "
            f"en {len(report['organizations_affected'])} organizacion(es)."
        ))
        self.stdout.write("")
        for org_id, count in sorted(report['pairs_by_organization'].items()):
            self.stdout.write(f"      org={org_id}: {count} par(es)")
        self.stdout.write("")
        for row in report['sample']:
            self.stdout.write(
                f"      - org={row['organization_id']} vet={row['veterinarian_id']}\n"
                f"          A {row['a']['public_id']} [{row['a']['status']}] "
                f"{row['a']['start']} -> {row['a']['end']}\n"
                f"          B {row['b']['public_id']} [{row['b']['status']}] "
                f"{row['b']['start']} -> {row['b']['end']}"
            )
        if report['sample_truncated']:
            self.stdout.write(f"      ... (muestra limitada a {SAMPLE_SIZE} pares)")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "  Remediacion HUMANA por clinica: mover, cancelar o desasignar\n"
            "  veterinario. Este comando no corrige nada a proposito.\n"
            "  Volver a correrlo hasta exit 0 antes de aplicar appointments/0014."
        ))
