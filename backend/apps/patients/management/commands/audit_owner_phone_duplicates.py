"""
audit_owner_phone_duplicates — expedientes que comparten teléfono normalizado.

INV-C (ADR p57 / decisión §4.8) convierte los duplicados de teléfono en un caso
**soportado**, no en un error a erradicar: dos expedientes con el mismo número
existen —una clínica los capturó así— y el sistema falla cerrado
(`owner_ambiguous`) en vez de elegir uno. Lo que hacía falta era **verlos**.

**Diagnóstico, no remediación.** Este comando no fusiona, no borra, no elige y
no propone. Un duplicado se resuelve solo si una persona de la clínica decide
qué expediente es cuál, con las herramientas que ya existen (`/pets`, edición de
cliente). Ninguna migración de este Item toca esos datos.

Alcance del conteo, idéntico al del resolvedor (`patients.services`):
  · por organización;
  · `is_generic=False` — el teléfono del genérico nunca es identidad (§4.12);
  · `phone_normalized IS NOT NULL` — sin clave no hay identidad por teléfono.

Exit codes (patrón `audit_stock_integrity`, para colgarlo de un cron sin
inventar convenciones):
  0  sin duplicados
  1  duplicados detectados
  2  error interno
"""
import json
import sys

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

SAMPLE_SIZE = 50


class Command(BaseCommand):
    help = (
        "Lista los teléfonos normalizados con más de un expediente por "
        "organización (INV-C). No corrige nada."
    )

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None,
                            help="Restringe a una organizacion id.")
        parser.add_argument('--json', action='store_true',
                            help="Emite un unico objeto JSON en vez de salida humana.")

    def handle(self, *args, **options):
        try:
            report = self._build_report(options)
        except Exception as exc:  # noqa: BLE001 — exit 2 es el contrato del comando
            self.stderr.write(self.style.ERROR(f"Error interno: {exc}"))
            sys.exit(2)

        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        else:
            self._print_human(report)

        sys.exit(report['exit_code'])

    def _build_report(self, options):
        from apps.patients.models import Owner

        org_filter = Q(organization_id=options['org']) if options['org'] else Q()

        # `all_objects` a propósito: un expediente desactivado sigue siendo un
        # dato que alguien debe ordenar, aunque el resolvedor (que usa el
        # manager con soft-delete) no lo cuente hoy.
        base = Owner.all_objects.filter(org_filter).filter(
            is_generic=False, phone_normalized__isnull=False,
        )

        groups = (
            base.values('organization_id', 'phone_normalized')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
            .order_by('organization_id', 'phone_normalized')
        )

        duplicate_groups = 0
        affected_owners = 0
        orgs = set()
        sample = []

        for row in groups.iterator(chunk_size=500):
            duplicate_groups += 1
            affected_owners += row['n']
            orgs.add(row['organization_id'])
            if len(sample) < SAMPLE_SIZE:
                owners = base.filter(
                    organization_id=row['organization_id'],
                    phone_normalized=row['phone_normalized'],
                ).values('public_id', 'name', 'phone', 'is_active').order_by('id')
                sample.append({
                    'organization_id': row['organization_id'],
                    'phone_normalized': row['phone_normalized'],
                    'count': row['n'],
                    'owners': [
                        {
                            'public_id': str(o['public_id']),
                            'name': o['name'],
                            'phone': o['phone'],
                            'is_active': o['is_active'],
                        }
                        for o in owners
                    ],
                })

        return {
            'duplicate_groups': duplicate_groups,
            'affected_owners': affected_owners,
            'affected_organizations': len(orgs),
            'sample': sample,
            'sample_truncated': duplicate_groups > len(sample),
            'exit_code': 1 if duplicate_groups else 0,
        }

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Duplicados de teléfono por expediente (INV-C, ADR p57)"
        ))
        self.stdout.write("")

        if not report['duplicate_groups']:
            self.stdout.write(self.style.SUCCESS(
                "  OK Ningún teléfono normalizado tiene más de un expediente."
            ))
            self.stdout.write("")
            self.stdout.write(f"Exit code: {report['exit_code']}")
            return

        self.stdout.write(self.style.WARNING(
            f"  {report['duplicate_groups']} teléfonos con más de un expediente "
            f"({report['affected_owners']} clientes, "
            f"{report['affected_organizations']} organizaciones)."
        ))
        self.stdout.write("")
        for group in report['sample']:
            self.stdout.write(
                f"  org={group['organization_id']} "
                f"tel={group['phone_normalized']} → {group['count']} expedientes"
            )
            for owner in group['owners']:
                estado = '' if owner['is_active'] else ' [inactivo]'
                self.stdout.write(
                    f"      - {owner['public_id']}  {owner['name']}  "
                    f"(capturado: \"{owner['phone']}\"){estado}"
                )
        if report['sample_truncated']:
            self.stdout.write("      … (muestra truncada)")

        self.stdout.write("")
        self.stdout.write(
            "  Estos casos responden `owner_ambiguous` en altas y en el "
            "importador hasta que una persona decida qué expediente es cuál."
        )
        self.stdout.write(
            "  El sistema NO los fusiona: no existe fusión automática ni asistida."
        )
        self.stdout.write("")
        self.stdout.write(f"Exit code: {report['exit_code']}")
