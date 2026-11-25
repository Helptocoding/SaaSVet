"""Estado de acceso de un integrante de Equipo (Fase 1, profesionalización).

Se deriva SOLO de campos que ya existen en ``User``; no hay estado propio ni
migración:

- ``is_active``
- ``password_must_change`` + ``password_temp_issued_at`` (ADR p21): con fecha de
  emisión es una contraseña temporal de restablecimiento o reactivación, que
  caduca a las 24 h; sin fecha es la contraseña inicial del alta, que no caduca.
- ``last_login``: lo registra ``services.record_user_access`` al iniciar sesión y
  al renovar la sesión, con precisión de una hora.

Prioridad (gana la primera que se cumple):

1. ``inactive`` — la cuenta no puede entrar.
2. ``temp_password_expired`` — misma regla que rechaza el login
   (``services.is_temp_password_expired``).
3. ``temp_password_active`` — contraseña temporal vigente.
4. ``pending_first_login`` — contraseña inicial y ningún acceso registrado.
5. ``password_change_pending`` — contraseña inicial y algún acceso registrado:
   entró, pero no completó el cambio obligatorio.
6. ``active`` — acceso normal.

Los accesos anteriores a esta fase no se registraron: ``last_login`` vacío solo
significa «sin accesos registrados».

Quién lo ve: solo quien gestiona personal (``can_manage_staff``). Es el mismo
criterio con el que el menú muestra Equipo.
"""
from __future__ import annotations

from apps.core.permissions import user_has_permission

# Mismo conjunto que `STAFF_MANAGEMENT_PERMS` del frontend
# (`frontend/src/features/staff/permissions.js`): quien tiene alguno ve Equipo y
# los datos de acceso de sus integrantes.
STAFF_MANAGEMENT_PERMISSIONS = (
    'staff.create',
    'staff.update',
    'staff.destroy',
    'staff.reset_password',
    'staff.reactivate',
    'staff.change_role',
    'staff.manage_absences',
    'staff.manage_permissions',
)

ACCESS_INACTIVE = 'inactive'
ACCESS_TEMP_PASSWORD_EXPIRED = 'temp_password_expired'
ACCESS_TEMP_PASSWORD_ACTIVE = 'temp_password_active'
ACCESS_PENDING_FIRST_LOGIN = 'pending_first_login'
ACCESS_PASSWORD_CHANGE_PENDING = 'password_change_pending'
ACCESS_ACTIVE = 'active'

ACCESS_STATUSES = (
    ACCESS_INACTIVE,
    ACCESS_TEMP_PASSWORD_EXPIRED,
    ACCESS_TEMP_PASSWORD_ACTIVE,
    ACCESS_PENDING_FIRST_LOGIN,
    ACCESS_PASSWORD_CHANGE_PENDING,
    ACCESS_ACTIVE,
)


def can_manage_staff(user) -> bool:
    """True si ``user`` tiene al menos un permiso de gestión de personal."""
    return any(user_has_permission(user, code) for code in STAFF_MANAGEMENT_PERMISSIONS)


def temp_password_expires_at(user):
    """Vencimiento de la contraseña temporal vigente, o ``None`` si no hay.

    La contraseña inicial del alta (sin ``password_temp_issued_at``) no vence.
    """
    from apps.users.services import TEMP_PASSWORD_VALIDITY

    if not user.password_must_change or user.password_temp_issued_at is None:
        return None
    return user.password_temp_issued_at + TEMP_PASSWORD_VALIDITY


def access_status(user) -> str:
    """Estado de acceso de ``user`` según la prioridad del docstring del módulo."""
    from apps.users.services import is_temp_password_expired

    if not user.is_active:
        return ACCESS_INACTIVE
    if user.password_must_change:
        if user.password_temp_issued_at is not None:
            if is_temp_password_expired(user):
                return ACCESS_TEMP_PASSWORD_EXPIRED
            return ACCESS_TEMP_PASSWORD_ACTIVE
        if user.last_login is None:
            return ACCESS_PENDING_FIRST_LOGIN
        return ACCESS_PASSWORD_CHANGE_PENDING
    return ACCESS_ACTIVE


def access_summary(user) -> dict:
    """Proyección pública del estado de acceso: sin hashes, tokens ni versión."""
    from rest_framework.fields import DateTimeField

    as_iso = DateTimeField().to_representation
    expires_at = temp_password_expires_at(user)
    return {
        'status': access_status(user),
        'last_login': as_iso(user.last_login) if user.last_login else None,
        'temp_password_expires_at': as_iso(expires_at) if expires_at else None,
    }
