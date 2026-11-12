"""Alta idempotente del superusuario de plataforma (ADMIN_SAAS).

Deuda B5, orden 6: antes corría como receptor de `post_migrate`. Ahora solo la invoca
el comando `bootstrap_superuser`, de forma explícita y con código de salida. El guard
anti-escalación es el de ADR p15 y no cambia.
"""
import logging
import os

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

logger = logging.getLogger('rbac.events')

# Resultados. El comando traduce cada uno a su código de salida.
CREATED = 'created'
EXISTING = 'existing'
BLOCKED = 'blocked'
MISSING_ENV = 'missing_env'
INCOMPLETE_ENV = 'incomplete_env'


def bootstrap_platform_superuser():
    """Crea o comprueba el superusuario de plataforma desde DJANGO_SUPERUSER_*.

    Guard anti-escalación (Issue #12 / ADR p15):
    - Si el username NO existe en DB → crea un superuser nuevo con role='ADMIN_SAAS'
      dentro de un atomic block; ante IntegrityError por dos ejecuciones simultáneas,
      re-fetch y reclasifica.
    - Si el username YA existe Y es el superuser de plataforma legítimo
      (is_superuser=True + is_staff=True + role='ADMIN_SAAS' + email coincide
      case-insensitive cuando se provee) → solo refresca is_active. NO resetea
      password (idempotencia de credenciales).
    - Si el username YA existe pero NO es el superuser de plataforma esperado
      (ej. una clínica registró un VET con ese username) → log CRITICAL y abort
      sin tocar al usuario. Sin esta guard, el antiguo signal escalaba cualquier
      usuario existente a superuser platform-wide y le reseteaba el password
      (CVSS 9.9).

    Devuelve CREATED, EXISTING, BLOCKED, MISSING_ENV o INCOMPLETE_ENV.
    """
    from apps.organizations.models import Organization

    username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
    email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

    if not username or not password:
        if username or password:
            # Solo uno de los dos seteado — config probablemente errónea.
            logger.warning("SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV", extra={
                "event": "SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV",
                "has_username": bool(username),
                "has_password": bool(password),
            })
            return INCOMPLETE_ENV
        return MISSING_ENV

    User = get_user_model()

    def _is_platform_superuser(user):
        """Predicado canónico — usado tanto en el path de fetch como en el
        post-race re-fetch. Mantener en un único lugar para evitar drift."""
        if not (user.is_superuser and user.is_staff):
            return False
        if getattr(user, 'role', None) != 'ADMIN_SAAS':
            return False
        if email and (user.email or '').lower() != email.lower():
            return False
        return True

    def _handle_existing(user, *, reason_if_blocked):
        if not _is_platform_superuser(user):
            logger.critical("SUPERUSER_BOOTSTRAP_SKIPPED", extra={
                "event": "SUPERUSER_BOOTSTRAP_SKIPPED",
                "reason": reason_if_blocked,
                "username": username,
                "existing_user_id": user.pk,
                "existing_role": getattr(user, 'role', None),
                "existing_org_id": user.organization_id,
                "existing_is_superuser": user.is_superuser,
                "existing_is_staff": user.is_staff,
            })
            return BLOCKED
        # Superuser plataforma legítimo: solo refrescar is_active si está inactivo.
        # NO resetear password.
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        return EXISTING

    existing = User.objects.filter(username=username).first()
    if existing is not None:
        return _handle_existing(existing, reason_if_blocked='username_collision_non_platform_user')

    # Usuario no existe → crear dentro de atomic. Si otra ejecución simultánea lo
    # creó en paralelo, IntegrityError dispara re-fetch y reclasifica.
    try:
        with transaction.atomic():
            org, _ = Organization.objects.get_or_create(name='Vet Care Internal')
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                role='ADMIN_SAAS',
                organization=org,
            )
        logger.info("SUPERUSER_BOOTSTRAP_CREATED", extra={
            "event": "SUPERUSER_BOOTSTRAP_CREATED",
            "username": username,
            "user_id": user.pk,
            "org_id": org.pk,
        })
        return CREATED
    except IntegrityError:
        # Otra ejecución creó el user entre filter().first() y create_superuser().
        # Re-fetch y aplicar el mismo predicado: si no calza con
        # is_platform_superuser, abort + log CRITICAL.
        raced = User.objects.filter(username=username).first()
        if raced is None:
            # IntegrityError por causa distinta a UNIQUE de username — re-raise.
            raise
        logger.warning("SUPERUSER_BOOTSTRAP_RACE_RESOLVED", extra={
            "event": "SUPERUSER_BOOTSTRAP_RACE_RESOLVED",
            "username": username,
            "user_id": raced.pk,
        })
        return _handle_existing(raced, reason_if_blocked='race_condition_created_unexpected_user')
