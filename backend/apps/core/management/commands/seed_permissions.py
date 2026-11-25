"""
seed_permissions — Puebla Permission, Role y permisos por organización.

Idempotente: se puede correr N veces sin efectos secundarios.
Se ejecuta automáticamente en cada release (`scripts/release.sh`), sin `--prune`.

Si agregas nuevos permisos en PERMISSION_CODES / PERMISSIONS,
el próximo deploy los crea automáticamente.

Antes de escribir revisa el estado de los roles, y aborta si un rol conservaría un
comodín (ADR p63). `--dry-run` muestra esa revisión sin escribir nada.

`--prune` (deuda B6, orden 6) borra los permisos de la base que ya no están en
`PERMISSION_CODES`, y con ellos sus concesiones en roles propios. Solo a mano, en una
ventana de mantenimiento; nunca en `release.sh`. Con `--dry-run` solo los lista. Nunca
poda comodines: los gobierna el preflight de ADR p63 y pueden ser una excepción
documentada.
"""
import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import (
    PERMISSION_CODES, PERMISSIONS, WILDCARD_ROLE_EXCEPTIONS, role_grants,
)
from apps.organizations.models import Organization

logger = logging.getLogger(__name__)
rbac_logger = logging.getLogger("rbac.events")

# Roles que pertenecen a la plataforma — no se crean por organización
_PLATFORM_ROLES = {"ADMIN_SAAS"}


def _is_wildcard(code):
    return code.endswith(".*")


class Command(BaseCommand):
    help = "Seed RBAC: permisos y roles de sistema por organización (idempotente)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Informa qué cambiaría y qué bloquea el seed, sin escribir nada.",
        )
        parser.add_argument(
            "--prune", action="store_true",
            help="Borra los permisos de la base que ya no están en el catálogo. "
                 "Con --dry-run solo los lista. Nunca borra comodines.",
        )

    def handle(self, *args, **options):
        blockers = self._preflight()
        if blockers:
            raise CommandError(
                "seed_permissions bloqueado, sin cambios:\n  " + "\n  ".join(blockers))
        orphans = self._report_orphans()
        if options["dry_run"]:
            if options["prune"]:
                self.stdout.write(f"  Se eliminarían {len(orphans)} permisos: {orphans}")
            self.stdout.write(self.style.SUCCESS("Preflight limpio. Sin cambios (--dry-run)."))
            return
        self._seed_permissions()
        self._seed_roles()
        if options["prune"]:
            self._prune()
        self.stdout.write(self.style.SUCCESS("seed_permissions completado"))

    def _org_role_codes(self):
        return [role for role in PERMISSIONS if role not in _PLATFORM_ROLES]

    def _preflight(self):
        blockers = []
        catalog = set(PERMISSION_CODES)
        managed = self._org_role_codes()
        for role_code in managed:
            for is_demo in (False, True):
                unknown = set(role_grants(role_code, is_demo=is_demo)) - catalog
                if unknown:
                    blockers.append(f"El rol {role_code} concede códigos fuera del catálogo: {sorted(unknown)}")

        users = get_user_model().objects.filter(is_active=True)
        roles = Role.objects.select_related("organization").prefetch_related("permissions")
        roles_by_org = {}
        for role in roles:
            roles_by_org.setdefault(role.organization_id, []).append(role)

        for org in Organization.objects.order_by("pk"):
            org_users = users.filter(organization=org)
            without_role = org_users.exclude(pk__in=UserRole.objects.values("user_id")).count()
            mismatched = org_users.filter(user_roles__isnull=False).exclude(
                user_roles__role__name=F("role")).distinct().count()
            self.stdout.write(
                f"Organización {org.public_id}: {org_users.filter(role='ADMIN').count()} usuarios ADMIN, "
                f"{without_role} activos sin UserRole, {mismatched} con UserRole distinto de su rol")

            for role in roles_by_org.get(org.pk, []):
                current = {p.code for p in role.permissions.all()}
                if role.name in managed:
                    target = set(role_grants(role.name, is_demo=org.is_demo))
                    gains, loses = sorted(target - current), sorted(current - target)
                    if gains or loses:
                        self.stdout.write(f"  {role.name}: gana {gains}; pierde {loses}")
                    continue
                self.stdout.write(f"  Rol no gestionado {role.name}: {len(current)} permisos")
                wildcards = sorted(code for code in current if _is_wildcard(code))
                if (wildcards and role.name not in _PLATFORM_ROLES
                        and (str(org.public_id), role.name) not in WILDCARD_ROLE_EXCEPTIONS):
                    blockers.append(
                        f"Organización {org.public_id}, rol {role.name}: conserva {wildcards}. "
                        "Retíralo o documenta una excepción en WILDCARD_ROLE_EXCEPTIONS.")

            multi_role = sum(
                1 for user in org_users.prefetch_related("user_roles")
                if len(user.user_roles.all()) > 1)
            if multi_role:
                self.stdout.write(f"  {multi_role} usuarios combinan varios roles: reciben su unión")
        return blockers

    def _seed_permissions(self):
        created = 0
        for code in PERMISSION_CODES:
            _, is_new = Permission.objects.get_or_create(code=code)
            if is_new:
                created += 1

        existing = len(PERMISSION_CODES) - created
        self.stdout.write(f"  Permissions: {created} creados, {existing} ya existían")

    def _seed_roles(self):
        perms_map = {p.code: p for p in Permission.objects.filter(code__in=PERMISSION_CODES)}

        # Orden determinista: sin él PostgreSQL devuelve el orden físico de las
        # filas, que cambia con lo que se haya borrado antes, y un seed que falla
        # a mitad dejaría hechas organizaciones distintas en cada corrida.
        orgs = list(Organization.objects.order_by("pk"))
        roles_created = 0
        roles_updated = 0

        for org in orgs:
            for role_code in self._org_role_codes():
                role, created = Role.objects.get_or_create(
                    name=role_code,
                    organization=org,
                    defaults={"is_system_role": True},
                )

                if not created and not role.is_system_role:
                    role.is_system_role = True
                    role.save(update_fields=["is_system_role"])

                role.permissions.set(
                    [perms_map[code] for code in role_grants(role_code, is_demo=org.is_demo)])

                if created:
                    roles_created += 1
                else:
                    roles_updated += 1

        self.stdout.write(
            f"  Roles: {roles_created} creados, {roles_updated} actualizados "
            f"en {len(orgs)} organización(es)"
        )

    def _orphan_permissions(self):
        # Los comodines (`*.*`, `recurso.*`) nunca están en el catálogo, pero los gobierna
        # el preflight de ADR p63 y pueden ser una excepción documentada: no se podan.
        return Permission.objects.exclude(code__in=PERMISSION_CODES).exclude(code__endswith=".*")

    def _report_orphans(self):
        orphans = sorted(self._orphan_permissions().values_list("code", flat=True))
        if orphans:
            self.stdout.write(f"Permisos fuera del catálogo: {len(orphans)} {orphans}")
        return orphans

    def _prune(self):
        with transaction.atomic():
            orphans = self._orphan_permissions()
            codes = sorted(orphans.values_list("code", flat=True))
            # Borrar el Permission retira también sus filas de Role.permissions.
            orphans.delete()
        rbac_logger.warning("SEED_PERMISSIONS_PRUNED", extra={
            "event": "SEED_PERMISSIONS_PRUNED", "count": len(codes), "codes": codes,
        })
        self.stdout.write(f"  Permisos podados: {len(codes)} {codes}")
