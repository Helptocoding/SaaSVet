"""
Sync MANUAL de los documentos legales con la landing (ADR p46, decisión 2).

Repos independientes: la landing mantiene el texto + la fecha "Última
actualización"; la app mantiene `LegalDocument.version` apuntando a esa versión.
NO hay dependencia en runtime entre proyectos.

Promover una versión a `is_current` es la decisión humana que dispara el
re-consentimiento (decisión 3: solo ante cambios materiales).

Uso:
  # Asegura las versiones vigentes por defecto (idempotente):
  python manage.py seed_legal_documents

  # Promover una versión NUEVA (cambio material → re-consentimiento):
  python manage.py seed_legal_documents --doc-type privacy \\
      --version 2026-12-01 --effective-date 2026-12-01 \\
      --url https://www.saaslyvet.com/aviso-de-privacidad
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.legal.models import LegalDocument


# (doc_type, version, effective_date, landing_url) — espejo del landing actual.
DEFAULTS = [
    ('privacy', '2026-06-24', '2026-06-24', 'https://www.saaslyvet.com/aviso-de-privacidad'),
    ('terms',   '2026-06-24', '2026-06-24', 'https://www.saaslyvet.com/terminos'),
]


class Command(BaseCommand):
    help = "Crea/promueve la versión vigente de los documentos legales (sync manual con la landing)."

    def add_arguments(self, parser):
        parser.add_argument('--doc-type', choices=['terms', 'privacy', 'cookies'])
        parser.add_argument('--version')
        parser.add_argument('--effective-date')
        parser.add_argument('--url')

    def handle(self, *args, **o):
        if o['doc_type']:
            missing = [k for k in ('version', 'effective_date', 'url') if not o[k]]
            if missing:
                raise CommandError(f"Faltan argumentos para bump puntual: {', '.join(missing)}")
            self._promote(o['doc_type'], o['version'], o['effective_date'], o['url'])
        else:
            for dt, ver, eff, url in DEFAULTS:
                self._promote(dt, ver, eff, url)

    def _promote(self, doc_type, version, effective_date, url):
        with transaction.atomic():
            # Demote la versión vigente anterior (si es otra) → solo una current.
            (LegalDocument.objects
             .filter(doc_type=doc_type, is_current=True)
             .exclude(version=version)
             .update(is_current=False))
            _, created = LegalDocument.objects.update_or_create(
                doc_type=doc_type, version=version,
                defaults={
                    'effective_date': date.fromisoformat(effective_date),
                    'landing_url': url,
                    'is_current': True,
                },
            )
        self.stdout.write(self.style.SUCCESS(
            f"{doc_type} v{version} → is_current (created={created})."
        ))
