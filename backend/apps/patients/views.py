from datetime import date, timedelta

from apps.core.datetime_utils import org_today_local

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id

from .models import Pet, Owner
from .serializers import PetSerializer, OwnerSerializer
from .archive import change_archive_state

# Mapeo grupo de especie → patrón regex (datos sucios de importación: el catálogo
# guarda 'canino'/'felino', pero archivos viejos traen 'Perro'/'PERRO'/'dog').
# Misma semántica que frontend/src/utils/petFilters.js (fuente única conceptual).
_CANINE_REGEX = r"perro|canino|dog"
_FELINE_REGEX = r"gato|felino|cat"

# Cortes de edad (años) → coherentes con getAgeGroup (frontend). Año = 365.25 días
# para empatar con el cálculo del frontend.
_AGE_BUCKETS = {
    "cachorro": (None, 1),   # < 1 año
    "joven": (1, 3),         # 1–3
    "adulto": (3, 8),        # 3–8
    "senior": (8, None),     # > 8
}


class PetViewSet(PublicIdLookupMixin, TenantQueryMixin, ModelViewSet):
    """
    Pacientes (mascotas). basename='patient' → permisos patient.*

    Paginación **opt-in** (ADR p42): solo se pagina cuando el cliente envía
    ``?page`` (la vista Mascotas /pets). Sin ``?page`` el endpoint conserva el
    contrato legacy de **array plano** que consumen los dropdowns SearchSelect
    (citas, recetas, POS) y las listas client-side (prescriptions, medical
    records) vía ``.then(ps => ps.map(...))``. Romperlo paginando globalmente
    rompería esos 6 consumidores — mismo carve-out que OwnerViewSet con ?search.

    Filtros server-side (la vista Mascotas escala a miles de registros sin
    descargar todo a memoria): ``?search`` (nombre/especie/raza/expediente/dueño/
    teléfono), ``?species`` (caninos|felinos), ``?sex``, ``?age``
    (cachorro|joven|adulto|senior), ``?owner=<public_id>``.
    """
    serializer_class = PetSerializer
    permission_classes = [HybridPermission]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        org = self.request.user.organization
        # select_related('owner') elimina el N+1: PetSerializer anida
        # OwnerSerializer → sin esto, serializar N mascotas = 1 + N queries.
        # for_organization() SIEMPRE primero (invariante tenant), luego el join.
        archived = (self.action in ('restore', 'archive') or
                    self.action == 'list' and self.request.query_params.get('archived') == 'true')
        if archived and self.request.user.role != 'ADMIN':
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Solo el administrador puede consultar archivados.')
        qs = (Pet.all_objects.filter(organization=org, is_active=False)
              if archived and self.action == 'list' and self.request.query_params.get('archived') == 'true'
              else Pet.all_objects.filter(organization=org) if archived
              else Pet.objects.for_organization(org)).select_related('owner')
        qs = self._apply_filters(qs, org).order_by("name", "id")

        params = self.request.query_params
        if params.get("page"):
            # Vista Mascotas: queryset completo filtrado → paginación (25).
            return qs
        # Contrato legacy: con ?search o ?owner, array plano acotado [:20]
        # (dropdowns). Sin filtros, la lista completa (consumidores client-side).
        if params.get("search", "").strip() or params.get("owner", "").strip():
            return qs[:20]
        return qs

    def paginate_queryset(self, queryset):
        # Paginar SOLO cuando el cliente pide ?page. Los consumidores legacy
        # (dropdowns + listas client-side) llaman sin ?page y esperan array
        # plano → devolver None para no envolver en {count,next,results}.
        if not self.request.query_params.get("page"):
            return None
        return super().paginate_queryset(queryset)

    def _apply_filters(self, qs, org):
        p = self.request.query_params
        search = p.get("search", "").strip()
        species = p.get("species", "").strip().lower()
        sex = p.get("sex", "").strip()
        age = p.get("age", "").strip().lower()
        owner_lookup = p.get("owner", "").strip()

        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(species__icontains=search)
                | Q(breed__icontains=search)
                | Q(legacy_id__icontains=search)
                | Q(owner__name__icontains=search)
                | Q(owner__phone__icontains=search)
            )
        if species in ("caninos", "canino", "dog", "perro"):
            qs = qs.filter(species__iregex=_CANINE_REGEX)
        elif species in ("felinos", "felino", "cat", "gato"):
            qs = qs.filter(species__iregex=_FELINE_REGEX)
        if sex in ("male", "female", "unknown"):
            qs = qs.filter(sex=sex)
        qs = self._apply_age_filter(qs, age, org)
        if owner_lookup:
            # Día 6 Fase 3: resolver Owner por public_id antes del filtro.
            owner = resolve_public_id(Owner.objects.for_organization(org), owner_lookup)
            qs = qs.filter(owner=owner)
        return qs

    def _apply_age_filter(self, qs, age, org):
        bucket = _AGE_BUCKETS.get(age)
        if not bucket:
            return qs
        younger_years, older_years = bucket
        # Día local de la clínica: `date.today()` es la fecha del servidor y
        # desplazaría los cortes de edad un día durante la ventana de desfase.
        today = org_today_local(org)
        # birth_date NULL queda excluido de todo bucket etario (comparación SQL
        # contra NULL = falso) — igual que getAgeGroup(null) → null en frontend.
        if younger_years is not None:
            # edad >= younger_years → nació hace al menos younger_years
            qs = qs.filter(birth_date__lte=today - timedelta(days=365.25 * younger_years))
        if older_years is not None:
            # edad < older_years → nació después de older_years atrás
            qs = qs.filter(birth_date__gt=today - timedelta(days=365.25 * older_years))
        return qs

    @action(detail=False, methods=["get"], permission_classes=[make_permission("patient.list")])
    def stats(self, request):
        """
        Conteos agregados de toda la clínica (no de la página actual): total,
        caninos, felinos. UNA query agregada (sin N+1, sin traer filas) — alimenta
        los stat-cards de /pets que ya no pueden calcularse client-side al paginar.
        """
        org = request.user.organization
        agg = Pet.objects.for_organization(org).aggregate(
            total=Count("id"),
            caninos=Count("id", filter=Q(species__iregex=_CANINE_REGEX)),
            felinos=Count("id", filter=Q(species__iregex=_FELINE_REGEX)),
        )
        return Response({
            "total": agg["total"] or 0,
            "caninos": agg["caninos"] or 0,
            "felinos": agg["felinos"] or 0,
        })

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_generic:
            # PR-4B: shape alineado al handler ProtectedError (code + message
            # en lugar del legacy `error`). Status 409 ya correcto.
            return Response(
                {
                    "code": "generic_resource_protected",
                    "message": "No se puede eliminar el paciente genérico del sistema.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        change_archive_state(actor=request.user, organization_id=request.user.organization_id,
                             kind='pet', public_id=instance.public_id, archive=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def archive(self, request, public_id=None):
        pet = change_archive_state(actor=request.user, organization_id=request.user.organization_id,
                                   kind='pet', public_id=public_id, archive=True)
        return Response(self.get_serializer(pet).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def restore(self, request, public_id=None):
        pet = change_archive_state(actor=request.user, organization_id=request.user.organization_id,
                                   kind='pet', public_id=public_id, archive=False)
        return Response(self.get_serializer(pet).data)

    def get_serializer_context(self):
        return {'request': self.request}


class OwnerViewSet(PublicIdLookupMixin, TenantQueryMixin, ModelViewSet):
    """
    Propietarios. basename='owner' → permisos owner.*
    Soporta ?search=<nombre>. Límite 20 cuando se filtra.

    P1-2: paginación PageNumber(25) en el listado completo.

    Búsqueda (`?search`) — ADR p44b: filtra por **nombre · teléfono · expediente**
    (`legacy_id`), todos `icontains` (índices GIN trigram en los tres campos). Con
    clínicas importadas un cliente se diferencia por su teléfono, no solo por el
    nombre repetido.

    El path `?search` **sin `?page`** sigue devolviendo array plano `[:20]`
    (contrato legacy de `SearchSelect`). **Con `?page`** sí pagina → habilita el
    "Ver más" de `EntitySearch` (mismo carve-out que `PetViewSet`).
    """
    serializer_class = OwnerSerializer
    permission_classes = [HybridPermission]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        archived = (self.action in ('restore', 'archive') or
                    self.action == 'list' and self.request.query_params.get('archived') == 'true')
        if archived and self.request.user.role != 'ADMIN':
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Solo el administrador puede consultar archivados.')
        qs = (Owner.all_objects.filter(organization=self.request.user.organization, is_active=False)
              if archived and self.action == 'list' and self.request.query_params.get('archived') == 'true'
              else Owner.all_objects.filter(organization=self.request.user.organization) if archived
              else Owner.objects.for_organization(self.request.user.organization))
        p = self.request.query_params
        is_generic = p.get("is_generic", "").strip()
        if is_generic == "true":
            qs = qs.filter(is_generic=True)
        elif is_generic == "false":
            qs = qs.filter(is_generic=False)
        search = p.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(legacy_id__icontains=search)
            )
            if not is_generic:
                # E4 del inventario (decisión §4.7.4, §4.12): la búsqueda existe
                # para que una PERSONA elija un cliente — el genérico no es un
                # cliente al que se le pueda colgar una mascota, y su teléfono
                # de relleno no es identidad de nadie. Se excluye salvo que el
                # llamador lo pida por su condición de genérico (`?is_generic=true`,
                # venta directa / ADR p25), nunca por coincidencia de número.
                qs = qs.filter(is_generic=False)
        # Owner no declara Meta.ordering → orden de heap. Orden estable para
        # paginación (name + id desempate).
        qs = qs.order_by("name", "id")
        # Dropdown legacy: ?search sin ?page → array plano [:20].
        if search and not p.get("page"):
            return qs[:20]
        return qs

    def paginate_queryset(self, queryset):
        # Búsqueda sin ?page → array plano [:20] (dropdowns SearchSelect que hacen
        # `.then(ps => ps.map(...))`). Con ?page se pagina (EntitySearch "Ver más").
        p = self.request.query_params
        if p.get("search", "").strip() and not p.get("page"):
            return None
        return super().paginate_queryset(queryset)

    def destroy(self, request, *args, **kwargs):
        # PR-4B D5: guard explícito antes de llegar al PROTECT-bound DB error.
        # El generic owner es el dummy walk-in usado por billing.services para
        # invoices sin cliente registrado. NUNCA debe borrarse. Sin este guard,
        # PROTECT lo bloquearía pero con un mensaje genérico de
        # `resource_has_dependencies` — esto da un mensaje específico y
        # accionable.
        instance = self.get_object()
        if instance.is_generic:
            return Response(
                {
                    "code": "generic_resource_protected",
                    "message": "No se puede eliminar el cliente genérico walk-in del sistema.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        change_archive_state(actor=request.user, organization_id=request.user.organization_id,
                             kind='owner', public_id=instance.public_id, archive=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def archive(self, request, public_id=None):
        owner = change_archive_state(actor=request.user, organization_id=request.user.organization_id,
                                     kind='owner', public_id=public_id, archive=True)
        return Response(self.get_serializer(owner).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def restore(self, request, public_id=None):
        owner = change_archive_state(actor=request.user, organization_id=request.user.organization_id,
                                     kind='owner', public_id=public_id, archive=False)
        return Response(self.get_serializer(owner).data)

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization
        )
