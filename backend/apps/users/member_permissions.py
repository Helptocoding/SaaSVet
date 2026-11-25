"""Permisos por integrante sobre los de su rol (ADR p69).

Reglas (decisiones del PO del 2026-11-25):

- Solo quien tiene ``staff.manage_permissions`` (solo ADMIN) concede o quita.
- Los permisos reservados a ADMIN (``permission_catalog.ADMIN_RESERVED``) no se
  conceden a otro rol ni se quitan a un ADMIN: «administrador» sigue siendo el
  rol ADMIN y la regla del último ADMIN (INV-J) no cambia.
- Nadie se quita a sí mismo permisos del área Administración.
- Se guarda solo la diferencia con el rol; el llamador envía el conjunto
  efectivo deseado.

``write_overrides`` es el único escritor de ``UserPermissionOverride`` y corre
dentro de la transacción de ``services.update_staff_member``.
"""
from __future__ import annotations

from rest_framework.exceptions import ValidationError

from apps.core.permission_catalog import ADMIN_RESERVED, ADMINISTRATION_CODES, PERMISSIONS as CATALOG
from apps.core.permissions import apply_overrides, expand_wildcards
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS as STATIC_ROLE_PERMISSIONS

MANAGE_PERMISSIONS = 'staff.manage_permissions'
EDITABLE_ROLES = ('ADMIN', 'VET', 'ASSISTANT')
_KNOWN = frozenset(PERMISSION_CODES)


def _concrete(codes):
    """Códigos concretos del catálogo (comodines expandidos)."""
    return expand_wildcards(codes) & _KNOWN


def role_default_codes(organization_id, role_name) -> set:
    """Los permisos del rol de sistema en esa clínica (los que siembra el seed)."""
    from apps.core.models import Role
    role = (Role.objects.filter(organization_id=organization_id, name=role_name,
                                is_system_role=True)
            .prefetch_related('permissions').first())
    if role is None:
        return _concrete(STATIC_ROLE_PERMISSIONS.get(role_name, []))
    return _concrete(p.code for p in role.permissions.all())


def role_defaults(organization_id) -> dict:
    return {role: sorted(role_default_codes(organization_id, role)) for role in EDITABLE_ROLES}


def _override_rows(user):
    from apps.core.models import UserPermissionOverride
    return list(UserPermissionOverride.objects.filter(user=user).values_list(
        'permission__code', 'effect'))


def _role_codes(user):
    from apps.core.models import UserRole
    return {code for code in UserRole.objects.filter(user=user).values_list(
        'role__permissions__code', flat=True) if code}


def effective_codes(user) -> set:
    """Permisos efectivos concretos, recalculados (no usa la caché por petición)."""
    return _concrete(apply_overrides(_role_codes(user), _override_rows(user)))


def overrides_of(user) -> dict:
    rows = _override_rows(user)
    return {
        'granted': sorted(code for code, effect in rows if effect == 'grant'),
        'revoked': sorted(code for code, effect in rows if effect == 'revoke'),
    }


def bulk_permissions(users) -> dict:
    """``{user_pk: {'permissions': [...], 'granted': [...], 'revoked': [...]}}`` en
    dos consultas, para la lista de Equipo (sin una consulta por fila)."""
    from apps.core.models import UserPermissionOverride, UserRole
    pks = [user.pk for user in users]
    role_codes, rows = {pk: set() for pk in pks}, {pk: [] for pk in pks}
    for user_id, code in (UserRole.objects.filter(user_id__in=pks)
                          .values_list('user_id', 'role__permissions__code')):
        if code:
            role_codes[user_id].add(code)
    for user_id, code, effect in (UserPermissionOverride.objects.filter(user_id__in=pks)
                                  .values_list('user_id', 'permission__code', 'effect')):
        rows[user_id].append((code, effect))
    result = {}
    for pk in pks:
        effective = _concrete(apply_overrides(role_codes[pk], rows[pk]))
        result[pk] = {
            'permissions': [code for code in PERMISSION_CODES if code in effective],
            'granted': sorted(code for code, effect in rows[pk] if effect == 'grant'),
            'revoked': sorted(code for code, effect in rows[pk] if effect == 'revoke'),
        }
    return result


def _labels(codes):
    return ', '.join(CATALOG[code][1] for code in PERMISSION_CODES if code in codes)


def plan_overrides(*, actor, target, role_name, desired, current_effective):
    """Valida el conjunto deseado y devuelve ``(concedidos, quitados)`` respecto del
    rol. ``current_effective`` son los permisos de la persona antes del cambio."""
    desired = set(desired)
    unknown = sorted(desired - _KNOWN)
    if unknown:
        raise ValidationError({'permissions': [f'Permisos desconocidos: {", ".join(unknown)}.']})
    if role_name != 'ADMIN' and desired & ADMIN_RESERVED:
        raise ValidationError({'permissions': [
            'Solo un administrador puede tener: ' + _labels(desired & ADMIN_RESERVED) + '.']})
    if role_name == 'ADMIN' and ADMIN_RESERVED - desired:
        raise ValidationError({'permissions': [
            'Un administrador siempre conserva: ' + _labels(ADMIN_RESERVED - desired) + '.']})
    if actor.pk == target.pk:
        lost = (set(current_effective) - desired) & ADMINISTRATION_CODES
        if lost:
            raise ValidationError({'permissions': [
                'No puedes quitarte permisos de administración: ' + _labels(lost) + '.']})
    base = role_default_codes(target.organization_id, role_name)
    return desired - base, base - desired


def kept_overrides_for_new_role(target, new_role):
    """Al cambiar de rol conservando ajustes: los mismos ajustes sobre el rol
    nuevo, sin los que ese rol ya no admite (reservados a ADMIN)."""
    rows = _override_rows(target)
    desired = _concrete(apply_overrides(role_default_codes(target.organization_id, new_role), rows))
    if new_role == 'ADMIN':
        desired |= ADMIN_RESERVED
    else:
        desired -= ADMIN_RESERVED
    return desired


def write_overrides(*, target, grants, revokes, actor):
    """Sustituye los ajustes de ``target``. Devuelve ``(antes, después)`` como
    ``{'granted': set, 'revoked': set}`` para el historial."""
    from apps.core.models import Permission, UserPermissionOverride
    before = overrides_of(target)
    UserPermissionOverride.objects.filter(user=target).delete()
    permissions = {p.code: p for p in Permission.objects.filter(code__in=set(grants) | set(revokes))}
    UserPermissionOverride.objects.bulk_create([
        UserPermissionOverride(organization_id=target.organization_id, user=target,
                               permission=permissions[code], effect=effect, granted_by=actor)
        for effect, codes in ((UserPermissionOverride.EFFECT_GRANT, grants),
                              (UserPermissionOverride.EFFECT_REVOKE, revokes))
        for code in sorted(codes) if code in permissions
    ])
    if hasattr(target, '_cached_permissions'):
        del target._cached_permissions
    return ({k: set(v) for k, v in before.items()},
            {'granted': set(grants), 'revoked': set(revokes)})


def delete_overrides(target):
    from apps.core.models import UserPermissionOverride
    UserPermissionOverride.objects.filter(user=target).delete()
    if hasattr(target, '_cached_permissions'):
        del target._cached_permissions
