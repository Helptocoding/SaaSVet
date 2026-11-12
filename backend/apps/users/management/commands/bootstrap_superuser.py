"""bootstrap_superuser — crea o comprueba el superusuario de plataforma (ADMIN_SAAS).

Lee DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD y, opcional,
DJANGO_SUPERUSER_EMAIL del entorno de ESTE proceso. En producción esas variables no
van en .env.prod (pre-launch, check 7): se pasan solo a este comando. Procedimiento en
docs/modules/organizations.md, sección «En VPS (produccion)».

Idempotente: si el superusuario legítimo ya existe, no cambia su contraseña.
Salida 0: creado o ya existente. Salida 1: variables ausentes o incompletas, o
colisión con un usuario que no es el superusuario de plataforma.
No forma parte de release.sh.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.users.bootstrap import (
    BLOCKED, CREATED, EXISTING, INCOMPLETE_ENV, MISSING_ENV, bootstrap_platform_superuser,
)

_ERRORS = {
    MISSING_ENV: 'Define DJANGO_SUPERUSER_USERNAME y DJANGO_SUPERUSER_PASSWORD para este comando.',
    INCOMPLETE_ENV: 'Falta DJANGO_SUPERUSER_USERNAME o DJANGO_SUPERUSER_PASSWORD: define ambos.',
    BLOCKED: (
        'El usuario indicado ya existe y no es el superusuario de plataforma. No se modificó. '
        'Revisa el evento SUPERUSER_BOOTSTRAP_SKIPPED.'
    ),
}
_SUCCESS = {
    CREATED: 'Superusuario de plataforma creado.',
    EXISTING: 'El superusuario de plataforma ya existía. Su contraseña no cambió.',
}


class Command(BaseCommand):
    help = 'Crea o comprueba el superusuario de plataforma desde DJANGO_SUPERUSER_*. Idempotente.'

    def handle(self, *args, **options):
        result = bootstrap_platform_superuser()
        if result in _ERRORS:
            raise CommandError(_ERRORS[result])
        self.stdout.write(self.style.SUCCESS(_SUCCESS[result]))
