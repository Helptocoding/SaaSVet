"""
core/permissions.py — Sistema RBAC de Vet Care SaaS
===================================================

FASES IMPLEMENTADAS:
  Fase 1 — RolePermission: control estático basado en PERMISSIONS dict
  Fase 3 — HybridPermission: DB-backed con cache + fallback estático

REGLAS:
  1. Permisos en formato "resource.action"
  2. has_object_permission SIEMPRE valida organization primero (multitenant)
  3. Acciones custom SIEMPRE definen required_permission en la view
  4. Nunca lógica de roles en views
  5. PERMISSION_CODES es la fuente única de verdad
  6. Wildcard global es "*.*"
  7. Excepciones documentadas explícitamente (ej: acceso a propio usuario)
"""
import logging

from django.core.cache import cache
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .permissions_codes import PERMISSIONS, PERMISSION_CODES
from .demo_reset import DEMO_RESET_FLAG_KEY

logger = logging.getLogger(__name__)
rbac_logger = logging.getLogger("rbac.events")


# ---------------------------------------------------------------------------
# Observabilidad — eventos RBAC estructurados (stdout en producción)
# ---------------------------------------------------------------------------
# Eventos emitidos:
#   RBAC_ALLOWED_DB          (INFO)    — permitido por roles en DB (fuente de verdad)
#   RBAC_FALLBACK_ALLOWED    (WARNING) — permitido por fallback estático (sin UserRole en DB)
#   RBAC_DENIED              (WARNING) — acceso denegado (cualquier fuente)
#   TENANT_MISMATCH_DETECTED (ERROR)   — intento de acceso a recurso de otra organización
#
# Los cuatro eventos permiten calcular:
#   fallback_rate = RBAC_FALLBACK_ALLOWED / (RBAC_ALLOWED_DB + RBAC_FALLBACK_ALLOWED)
#   denied_rate   = RBAC_DENIED / total_requests (por endpoint)
#
# Gate Fase 4: ausencia de RBAC_FALLBACK_ALLOWED y TENANT_MISMATCH_DETECTED en 7 días
# con ≥500 requests totales y ≥1 request por cada endpoint crítico.

import uuid

from apps.core.request_context import get_request_id


def _get_request_id(request) -> str:
    """
    ID de correlación por request — agrupa todos los eventos RBAC de una misma
    petición HTTP.

    P1-5 A1: reusa el request_id del RequestIDMiddleware (el mismo X-Request-ID
    que viaja frontend → header → logs → Sentry → respuesta), de modo que exista
    UN solo identificador por request en toda la observabilidad. El fallback al
    uuid corto cacheado solo aplica si la petición no pasó por el middleware
    (escenarios sin HTTP / tests que invocan el permission directo).
    """
    rid = get_request_id()
    if rid:
        return rid
    if not hasattr(request, "_rbac_request_id"):
        request._rbac_request_id = uuid.uuid4().hex[:12]
    return request._rbac_request_id


def _rbac_extra(request, user, required: str | None) -> dict:
    return {
        "request_id": _get_request_id(request),
        "user_id": getattr(user, "id", None),
        "organization_id": getattr(user, "organization_id", None),
        "role": getattr(user, "role", None),
        "endpoint": getattr(request, "path", None),
        "method": getattr(request, "method", None),
        "required_permission": required,
    }


# ---------------------------------------------------------------------------
# ADR p49 — ventana de mantenimiento del tenant demo
# ---------------------------------------------------------------------------
class DemoResetInProgress(APIException):
    """503 emitido durante la ventana de reset del tenant demo (ADR p49 §9)."""
    status_code = 503
    default_detail = "La demo se está reiniciando, vuelve a intentar en unos segundos."
    default_code = "demo_resetting"


def _demo_reset_blocks(request) -> bool:
    """
    True si una ESCRITURA de un usuario de la org demo debe rechazarse porque hay
    un reset en curso (flag en cache, lo pone `seed_demo_clinic --reset`). Las
    lecturas (métodos safe) y los tenants reales nunca se bloquean. Camino común
    = short-circuit barato (no toca la cache salvo write de usuario demo).
    """
    if request.method in SAFE_METHODS:
        return False
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return False
    org = getattr(user, 'organization', None)
    if not bool(getattr(org, 'is_demo', False)):
        return False
    return bool(cache.get(DEMO_RESET_FLAG_KEY))


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def user_has_permission(user, perm_code: str) -> bool:
    """
    Check if a user has a specific permission code.
    
    Used for non-view validation (e.g., walk-in appointment veterinarian validation).
    
    Returns True if:
      - user is superuser
      - user has the permission via DB-backed roles (UserRole + Role + Permission)
      - user has the permission via static fallback (PERMISSIONS dict)
    
    Args:
        user: Django User instance
        perm_code: Permission code in "resource.action" format (e.g., "appointments.create_walkin")
    
    Returns:
        bool: True if user has permission, False otherwise
    """
    if not user.is_authenticated:
        return False
    
    if user.is_superuser:
        return True
    
    # Try DB-backed permissions first
    db_perms = _get_cached_permissions(user)
    if db_perms is not None:
        return _is_allowed(perm_code, db_perms)
    
    # Fallback to static permissions
    static_perms = PERMISSIONS.get(user.role, [])
    return _is_allowed(perm_code, static_perms)


def user_has_permission_strict(user, perm_code: str) -> bool:
    """
    Strict permission check using DB-backed roles ONLY.

    Behavior:
      - Returns True when the user is superuser.
      - Returns True if the permission is present in the user's DB-backed
        roles (UserRole -> Role -> Permission).
      - Returns False when the user has NO UserRole in DB (no fallback to
        the legacy static PERMISSIONS mapping).

    Architectural note (IMPORTANT):
      - Use `user_has_permission(...)` for checks about the request.user
        (this function performs DB lookup first and *falls back* to the
        static PERMISSIONS mapping while the project is still in the
        migration/fallback phase).
      - Use `user_has_permission_strict(...)` for cross-user validations,
        i.e. when you validate permissions of another user (assigned
        veterinarian, owner, etc.). These checks MUST NOT use the legacy
        fallback because that could grant implicit rights based on the
        historical `User.role` field.

    This separation prevents accidental privilege escalation when code
    validates other users' permissions.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    db_perms = _get_cached_permissions(user)
    if db_perms is None:
        return False
    return _is_allowed(perm_code, db_perms)


# Backwards compatibility alias (deprecated): prefer `user_has_permission_strict`
def user_has_permission_db_only(user, perm_code: str) -> bool:
    """Deprecated alias for user_has_permission_strict.

    Keep for backward compatibility; new code should call
    `user_has_permission_strict` directly.
    """
    return user_has_permission_strict(user, perm_code)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _method_to_action(method: str, view) -> str:
    """
    Deriva el nombre de acción DRF a partir del método HTTP.
    Usado como fallback cuando la view no es un ViewSet.
    """
    method = method.upper()
    if method == "GET":
        # Distingue list vs retrieve por la presencia de pk/id en kwargs
        kwargs = getattr(view, "kwargs", {}) or {}
        if any(k in kwargs for k in ("pk", "id")):
            return "retrieve"
        return "list"
    return {
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "destroy",
    }.get(method, "list")


def _resolve_required(request, view) -> str | None:
    """
    Determina el permiso requerido para una request+view.

    Orden de resolución:
      1. view.required_permission (siempre tiene precedencia — acciones custom)
      2. f"{resource}.{action}" construido desde basename/resource_name + action
      3. None si no se puede determinar (view sin recurso definido)
    """
    required = getattr(view, "required_permission", None)
    if required:
        return required

    # Soporte ViewSets (basename) y generic views (resource_name)
    resource = getattr(view, "basename", None) or getattr(view, "resource_name", None)
    if not resource:
        return None

    # Soporte ViewSets (action) y generic views (derivado del método HTTP)
    action = getattr(view, "action", None) or _method_to_action(request.method, view)
    return f"{resource}.{action}"


def _is_allowed(required: str, allowed: list) -> bool:
    """
    Evalúa si `required` está cubierto por `allowed`.
    Soporta wildcards: "*.*" (global) y "resource.*" (por recurso).
    """
    if not required:
        return True

    resource = required.split(".")[0]
    return (
        "*.*" in allowed
        or f"{resource}.*" in allowed
        or required in allowed
    )


def _get_cached_permissions(user) -> "set | None":
    if hasattr(user, "_cached_permissions"):
        return user._cached_permissions
    from apps.core.models import UserRole
    user_roles = UserRole.objects.select_related("role").prefetch_related(
        "role__permissions"
    ).filter(user=user)
    if not user_roles.exists():
        user._cached_permissions = None
        return None
    perms: set[str] = set()
    for ur in user_roles:
        perms.update(ur.role.permissions.values_list("code", flat=True))
    user._cached_permissions = perms
    return perms


# ---------------------------------------------------------------------------
# Fase 1 — RolePermission (control estático)
# ---------------------------------------------------------------------------

class RolePermission(BasePermission):
    """
    Control de acceso basado en el rol estático del usuario (campo role en User).

    Fuente de permisos: PERMISSIONS dict en permissions_codes.py.

    Compatible con:
      - ViewSets (usa view.basename y view.action)
      - Generic class-based views (usa view.resource_name + método HTTP)
      - Function-based views (usa view.required_permission establecido en el handler)

    Prioridad de resolución del permiso requerido:
      view.required_permission > basename/resource_name + action
    """

    def has_permission(self, request, view) -> bool:
        if not request.user.is_authenticated:
            return False

        # Superadmin de plataforma siempre tiene acceso
        if request.user.is_superuser:
            return True

        role = request.user.role  # noqa: F841 (usado implícitamente vía PERMISSIONS)
        required = _resolve_required(request, view)

        # Si no se puede determinar el recurso, denegar acceso (fail-closed).
        # Toda view con RolePermission debe definir resource_name o required_permission.
        if required is None:
            return False

        allowed = PERMISSIONS.get(role, [])
        result = _is_allowed(required, allowed)
        extra = _rbac_extra(request, request.user, required)
        if result:
            rbac_logger.warning("RBAC_FALLBACK_ALLOWED", extra=extra)
        else:
            rbac_logger.warning("RBAC_DENIED", extra=extra)
        return result

    def has_object_permission(self, request, view, obj) -> bool:
        # Regla 1 (SIEMPRE PRIMERO): aislamiento multitenant
        if hasattr(obj, "organization_id"):
            if obj.organization_id != request.user.organization_id:
                rbac_logger.error("TENANT_MISMATCH_DETECTED", extra={
                    **_rbac_extra(request, request.user, _resolve_required(request, view)),
                    "resource_org": obj.organization_id,
                })
                return False

        # Excepción documentada: el usuario siempre accede a su propio registro
        if hasattr(obj, "user_id") and obj.user_id == request.user.id:
            return True  # acceso al propio usuario

        return self.has_permission(request, view)


# ---------------------------------------------------------------------------
# Fase 3 — HybridPermission (DB + cache + fallback estático)
# ---------------------------------------------------------------------------

class HybridPermission(BasePermission):
    """
    Control de acceso híbrido: consulta permisos en DB cuando existen,
    cae en fallback estático (PERMISSIONS dict) cuando no hay roles en DB.

    Cache: los permisos se almacenan en user._cached_permissions durante
    el ciclo de vida del request (no persiste entre requests).

    El fallback estático emite un WARNING por usuario — cuando los logs
    lleguen a 0, es seguro eliminar el fallback y el campo User.role.
    """

    def has_permission(self, request, view) -> bool:
        if not request.user.is_authenticated:
            return False

        # ADR p49: ventana de mantenimiento del demo. Embebido aquí (igual que el
        # must-change y el legal gate) porque las views declaran su propio
        # permission_classes y pisan el DEFAULT. Solo escrituras de la org demo y
        # solo durante un reset en curso → 503 (las lecturas pasan: MVCC).
        if _demo_reset_blocks(request):
            raise DemoResetInProgress()

        # ADR p21: must_change_password gate (embedded here because DRF
        # ignores ``DEFAULT_PERMISSION_CLASSES`` once a view declares its
        # own ``permission_classes`` — and ~every view in the project
        # does. Embedding in HybridPermission propagates to every view
        # that uses it (directly or via ``make_permission``).
        if getattr(request.user, 'password_must_change', False):
            path = request.path
            allowed = any(
                path == w or path.startswith(w)
                for w in _MUST_CHANGE_WHITELIST
            )
            if not allowed:
                rbac_logger.warning("MUST_CHANGE_PASSWORD_BLOCKED", extra={
                    "event": "MUST_CHANGE_PASSWORD_BLOCKED",
                    "actor_id": request.user.pk,
                    "actor_username": request.user.username,
                    "path": path,
                    "method": request.method,
                })
                return False

        if request.user.is_superuser:
            return True

        # ADR p46: LegalAcceptanceGate — bloquea hasta aceptar los documentos
        # legales vigentes requeridos por el rol. Va DESPUÉS del must-change
        # (orden: credencial → legal) y DESPUÉS de is_superuser (ADMIN_SAAS
        # exento). Embebido aquí por la misma razón que el must-change: las
        # views declaran su propio permission_classes y pisan el DEFAULT.
        if _legal_blocks(request):
            _log_legal_blocked(request)
            return False

        required = _resolve_required(request, view)
        if required is None:
            return False

        db_perms = self._get_db_permissions(request.user)

        if db_perms is not None:
            result = _is_allowed(required, db_perms)
            extra = _rbac_extra(request, request.user, required)
            if result:
                rbac_logger.info("RBAC_ALLOWED_DB", extra=extra)
            else:
                rbac_logger.warning("RBAC_DENIED", extra=extra)
            return result

        # Fallback estático — usuario sin UserRole en DB
        static_perms = PERMISSIONS.get(request.user.role, [])
        result = _is_allowed(required, static_perms)
        extra = _rbac_extra(request, request.user, required)
        if result:
            rbac_logger.warning("RBAC_FALLBACK_ALLOWED", extra=extra)
        else:
            rbac_logger.warning("RBAC_DENIED", extra=extra)
        return result

    def has_object_permission(self, request, view, obj) -> bool:
        # Regla 1 (SIEMPRE PRIMERO): aislamiento multitenant
        if hasattr(obj, "organization_id"):
            if obj.organization_id != request.user.organization_id:
                rbac_logger.error("TENANT_MISMATCH_DETECTED", extra={
                    **_rbac_extra(request, request.user, _resolve_required(request, view)),
                    "resource_org": obj.organization_id,
                })
                return False

        return self.has_permission(request, view)

    def _get_db_permissions(self, user) -> "set | None":
        return _get_cached_permissions(user)


# ---------------------------------------------------------------------------
# API pública — lista de permisos para el frontend (/api/me/)
# ---------------------------------------------------------------------------

def build_permissions_list(user) -> list[str]:
    """
    Retorna lista de códigos de permiso activos para el usuario.
    Usa el mismo cache (user._cached_permissions) que HybridPermission.
    Reutilizable, testeable. Consumida por MeView.
    """
    return [
        code for code in PERMISSION_CODES
        if user_has_permission(user, code)
    ]


# ---------------------------------------------------------------------------
# Factory: permiso específico para FBVs
# ---------------------------------------------------------------------------

def make_permission(code: str) -> type:
    """
    Crea una clase Permission que exige un código específico.

    Uso en function-based views que no pueden establecer resource_name:

        @api_view(['PATCH'])
        @permission_classes([make_permission("invoice.confirm")])
        def confirm_invoice(request, pk):
            ...

    Regla 3: acciones custom SIEMPRE definen required_permission.
    """
    class SpecificPermission(HybridPermission):
        def has_permission(self, request, view):
            view.required_permission = code
            return super().has_permission(request, view)

    SpecificPermission.__name__ = f"Permission_{code.replace('.', '_')}"
    return SpecificPermission


# ---------------------------------------------------------------------------
# Credential-lifecycle gate (ADR p21)
# ---------------------------------------------------------------------------

# URL paths the user is allowed to reach while `password_must_change=True`.
# Everything else returns 403 with a structured payload that the frontend
# uses to force-redirect to the change-password screen.
#
# Whitelist rationale:
#   /api/users/change-password/  — the exit door
#   /api/me/                     — frontend needs current user data to render
#   /api/token/refresh/          — keep token refresh alive while changing
#   /api/token/                  — login itself
#   /api/auth/                   — any future auth flows (forgot-password, etc.)
_MUST_CHANGE_WHITELIST = (
    '/api/users/change-password/',
    '/api/me/',
    '/api/token/refresh/',
    '/api/token/',
)


# ---------------------------------------------------------------------------
# Legal acceptance gate (ADR p46)
# ---------------------------------------------------------------------------

# Rutas alcanzables aún con aceptación legal pendiente: el namespace legal
# (ver/aceptar) + el mismo conjunto del must-change (un user puede tener ambos
# gates pendientes; no debe quedar lockeado).
_LEGAL_WHITELIST = (
    '/api/legal/',                  # GET documentos vigentes + POST aceptar
    '/api/users/change-password/',
    '/api/me/',
    '/api/token/refresh/',
    '/api/token/',
)


def _legal_blocks(request) -> bool:
    """
    True si el user autenticado debe aceptar documentos legales vigentes y la
    ruta NO está whitelisted. Cachea el resultado en el user para el ciclo del
    request (evita doble query si has_permission corre más de una vez). Import
    perezoso de apps.legal para no crear ciclo core→legal a nivel de módulo.
    """
    user = request.user
    if user.is_superuser:
        return False
    path = request.path
    for w in _LEGAL_WHITELIST:
        if path == w or path.startswith(w):
            return False
    if not hasattr(user, '_legal_required'):
        from apps.legal.services import legal_acceptance_required
        user._legal_required = legal_acceptance_required(user)
    return user._legal_required


def _log_legal_blocked(request) -> None:
    rbac_logger.warning("LEGAL_ACCEPTANCE_REQUIRED_BLOCKED", extra={
        "event": "LEGAL_ACCEPTANCE_REQUIRED_BLOCKED",
        "actor_id": request.user.pk,
        "actor_username": request.user.username,
        "path": request.path,
        "method": request.method,
    })


class LegalAcceptanceGate(BasePermission):
    """
    Standalone para views que usan el DEFAULT_PERMISSION_CLASSES (no
    HybridPermission). Las views de dominio usan HybridPermission, que embebe
    el mismo chequeo (mismo patrón que MustChangePasswordGate). Server-side
    autoritativo: el frontend redirige por UX, pero un cliente curl choca aquí.
    """

    message = "Debes aceptar los documentos legales vigentes para continuar."

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return True  # IsAuthenticated maneja unauth — no es lo nuestro
        if _legal_blocks(request):
            _log_legal_blocked(request)
            return False
        return True


class MustChangePasswordGate(BasePermission):
    """
    Blocks every endpoint outside the whitelist when the authenticated
    user has ``password_must_change=True``. Pair with ``IsAuthenticated``
    in ``DEFAULT_PERMISSION_CLASSES`` so unauthenticated requests still
    fall through normally.

    Returning 403 here (rather than the alternative of allowing access
    and trusting the frontend redirect) is critical — a curl/Postman
    client can ignore frontend logic entirely. The gate is the
    authoritative enforcement point.
    """

    message = "Cambia tu contraseña antes de continuar."

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return True  # IsAuthenticated handles unauth — not our concern
        if not getattr(user, 'password_must_change', False):
            return True

        # Allow listed paths through so the user can actually exit the
        # must-change state.
        path = request.path
        for whitelisted in _MUST_CHANGE_WHITELIST:
            if path == whitelisted or path.startswith(whitelisted):
                return True

        rbac_logger.warning("MUST_CHANGE_PASSWORD_BLOCKED", extra={
            "event": "MUST_CHANGE_PASSWORD_BLOCKED",
            "actor_id": user.pk,
            "actor_username": user.username,
            "path": path,
            "method": request.method,
        })
        return False


class NotDemoAccount(BasePermission):
    """
    Blocks the action for users that belong to the demo tenant
    (``organization.is_demo=True``). Use on endpoints whose effect must be
    inert in the public demo: self-service password change (would lock the
    shared demo credentials) and data import (would pollute the demo dataset).

    Enforcement lives here, not only in the frontend (which merely hides the
    option): a curl/Postman client must be rejected too. Real tenants
    (``is_demo=False``) and the platform operator (no org) pass through.
    """

    message = "Esta acción no está disponible en la cuenta demo."
    code = "demo_account_restricted"

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return True  # IsAuthenticated handles unauth — not our concern
        org = getattr(user, 'organization', None)
        return not bool(getattr(org, 'is_demo', False))


class DemoResetGate(BasePermission):
    """
    ADR p49 — ventana de mantenimiento del tenant demo, para las views que SÍ
    usan el DEFAULT_PERMISSION_CLASSES (las que no declaran permission_classes
    propio). Las views RBAC pisan el default con HybridPermission, que embebe el
    mismo check en su has_permission. Mantener ambos espeja exactamente el patrón
    de MustChangePasswordGate / LegalAcceptanceGate.
    """

    def has_permission(self, request, view):
        if _demo_reset_blocks(request):
            raise DemoResetInProgress()
        return True
