from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.datetime_utils import (
    filter_by_local_day,
    get_context_timezone,
    local_day_bounds_utc,
    org_now_utc,
    org_today_local,
)
from apps.core.permissions import make_permission
from apps.analytics.services import (
    _analytics_queryset,
    _provenance_breakdown,
    ANCHOR_REGISTRY,
)
from apps.analytics.models import METRICS_SCHEMA_VERSION
from apps.medical_records.models import MedicalRecord
from apps.appointments.models import Appointment


# ---------------------------------------------------------------------------
# Analytics anchor health — operations / monitoring endpoint.
# Restringido a ADMIN_SAAS (rol estático platform-wide; el contrato analítico
# es responsabilidad del operador del SaaS, no de admins por organización).
# Devuelve provenance distribution + invariant findings + decay alerts.
# Diseñado para consumo por monitoring stack o por humano via curl.
# ---------------------------------------------------------------------------

LEGACY_DECAY_THRESHOLD_DAYS = 90
FALLBACK_WARN_PERCENT = 5.0


class IsAdminSaaS(permissions.BasePermission):
    """Operador de plataforma: superuser Y staff Y role=ADMIN_SAAS.

    Las tres condiciones, no solo el rol (auditoría run-1, unidad comodín).
    `analytics_health` es el único endpoint cross-tenant de lectura del SaaS:
    acepta `?org=<id>` y, SIN ese parámetro, consulta todas las organizaciones
    a la vez (`org_filter = Q()`). Comprobar únicamente `role` hacía que el
    aislamiento de esa ruta dependiera de que nadie creara jamás un ADMIN_SAAS
    sin `is_superuser` — p. ej. un técnico de soporte con el rol y sin
    superuser leería los volúmenes de cualquier clínica.

    No era explotable por API: ninguna ruta escribe `User.role`
    (`CreateEmployeeSerializer` restringe sus choices a ADMIN/VET/ASSISTANT,
    `UserSerializer` se usa solo como salida y no existe vista de
    actualización de staff). Se endurece porque esa ausencia de camino es
    una propiedad del código de hoy, no un invariante declarado.

    Predicado idéntico a `apps.platform.permissions.IsPlatformOperator`, que
    NO se importa aquí a propósito: `platform` es la frontera cross-tenant y
    `dashboard` no debe depender de ella. La duplicación la vigila
    `tests/test_platform_predicate_parity.py`, que importa ambas en test.
    """

    message = "Solo operadores de plataforma."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(
            user.is_superuser
            and user.is_staff
            and getattr(user, 'role', None) == 'ADMIN_SAAS'
        )


def _trust_score(provenance, invariant_violations, unresolved_count):
    """Compute single-letter trust score per the audit doc convention."""
    if invariant_violations > 0:
        return 'F'
    if unresolved_count > 0:
        return 'C'
    fallback = sum(
        v for k, v in provenance.items() if k == 'fallback'
    )
    legacy = sum(v for k, v in provenance.items() if k == 'legacy')
    total = sum(provenance.values()) or 1
    fallback_pct = (fallback / total) * 100
    if fallback_pct > FALLBACK_WARN_PERCENT:
        return 'B'
    if legacy > 0:
        return 'B'
    return 'A'


def _resolve_model(dotted):
    """Resolve 'app_label.ModelName' → model class."""
    from django.apps import apps
    app_label, model_name = dotted.split('.')
    return apps.get_model(app_label, model_name)


@api_view(['GET'])
@permission_classes([IsAdminSaaS])
def analytics_health(request):
    """
    Returns a JSON snapshot of analytics anchor health for monitoring.

    Response shape:
      {
        "anchors": {
          "invoice.paid_at": {"service": N, "fallback": N, "legacy": N, ...},
          ...
        },
        "invariant_violations": {
          "invoice.paid_status_requires_paid_at": N,
          ...
        },
        "unresolved_provenance": N,
        "walk_in_suspect_count": N,
        "legacy_decay_alerts": [
          {"anchor": "invoice.paid_at", "rows": N,
           "oldest_legacy_age_days": N, "threshold_days": 90,
           "severity": "warning|critical"}
        ],
        "fallback_warnings": [...],
        "trust_score_per_anchor": {"invoice.paid_at": "A", ...},
        "checked_at": "2026-05-09T..."
      }
    """
    from apps.billing.models import Invoice
    from apps.medical_records.models import MedicalRecord
    from apps.appointments.models import Appointment

    org_id = request.query_params.get('org')
    org_filter = Q(organization_id=org_id) if org_id else Q()
    now = timezone.now()
    decay_cutoff = now - timedelta(days=LEGACY_DECAY_THRESHOLD_DAYS)

    anchors = {
        f"{spec.model.split('.')[1].lower()}.{spec.anchor_field}":
            _provenance_breakdown(
                _analytics_queryset(
                    _resolve_model(spec.model)
                ).filter(org_filter),
                spec.source_field,
            )
        for spec in ANCHOR_REGISTRY
    }

    invariants = {
        'invoice.paid_status_requires_paid_at':
            _analytics_queryset(Invoice).filter(
                org_filter, status='paid', paid_at__isnull=True,
            ).count(),
        'invoice.posted_at_required':
            _analytics_queryset(Invoice).filter(
                org_filter, posted_at__isnull=True,
            ).count(),
        'invoice.voided_status_requires_voided_at':
            _analytics_queryset(Invoice).filter(
                org_filter, status='voided', voided_at__isnull=True,
            ).count(),
        'medicalrecord.closed_status_requires_closed_at':
            _analytics_queryset(MedicalRecord).filter(
                org_filter, status='closed', closed_at__isnull=True,
            ).count(),
    }

    unresolved = _analytics_queryset(Invoice).filter(
        org_filter & (Q(posted_at_source='unresolved') | Q(voided_at_source='unresolved'))
    ).count()

    walk_in_suspect = (
        _analytics_queryset(Appointment)
        .filter(org_filter, walk_in=False, status__in=['in_progress', 'done'])
        .exclude(status_changes__from_status='scheduled')
        .distinct()
        .count()
    )

    # ---- Decay alerts ----
    decay_alerts = []
    fallback_warnings = []

    decay_specs = [
        (_resolve_model(spec.model), spec.source_field, spec.anchor_field,
         f"{spec.model.split('.')[1].lower()}.{spec.anchor_field}")
        for spec in ANCHOR_REGISTRY
    ]
    for model, src_field, anchor_field, label in decay_specs:
        legacy_qs = _analytics_queryset(model).filter(org_filter, **{src_field: 'legacy'})
        legacy_count = legacy_qs.count()
        if legacy_count == 0:
            continue
        oldest = legacy_qs.order_by(anchor_field).values_list(anchor_field, flat=True).first()
        age_days = (now - oldest).days if oldest else 0
        decay_alerts.append({
            'anchor': label,
            'rows': legacy_count,
            'oldest_legacy_age_days': age_days,
            'threshold_days': LEGACY_DECAY_THRESHOLD_DAYS,
            'severity': 'critical' if age_days > LEGACY_DECAY_THRESHOLD_DAYS else 'warning',
        })

    # ---- Fallback % warnings ----
    for label, dist in anchors.items():
        total = sum(dist.values())
        if total == 0:
            continue
        fb = dist.get('fallback', 0)
        pct = (fb / total) * 100
        if pct > FALLBACK_WARN_PERCENT:
            fallback_warnings.append({
                'anchor': label,
                'fallback_count': fb,
                'total': total,
                'percent': round(pct, 2),
                'threshold_percent': FALLBACK_WARN_PERCENT,
            })

    trust_per = {}
    for label in anchors:
        related_invariant = sum(
            v for k, v in invariants.items() if k.startswith(label.split('.')[0])
        )
        trust_per[label] = _trust_score(
            anchors[label],
            related_invariant,
            unresolved if label.startswith('invoice') else 0,
        )

    return Response({
        'anchors': anchors,
        'invariant_violations': invariants,
        'unresolved_provenance': unresolved,
        'walk_in_suspect_count': walk_in_suspect,
        'legacy_decay_alerts': decay_alerts,
        'fallback_warnings': fallback_warnings,
        'trust_score_per_anchor': trust_per,
        'checked_at': now,
    })


@api_view(['GET'])
@permission_classes([make_permission("dashboard.view")])
def dashboard_stats(request):
    from apps.appointments.models import Appointment
    from apps.medical_records.models import MedicalRecord
    from apps.inventory.models import Product

    org = request.user.organization
    if org is None:
        raise PermissionDenied("User has no organization assigned")
    today_local = org_today_local(org)
    now_utc = org_now_utc(org)

    appointments_qs = Appointment.objects.for_organization(org).filter(
        status__in=['scheduled', 'done'],
    )
    appointments_today = filter_by_local_day(
        appointments_qs,
        'start_datetime',
        org,
        today_local,
    ).count()

    recent_records = MedicalRecord.objects.for_organization(org).order_by('-created_at').values(
        'id', 'pet__name', 'diagnosis', 'created_at',
        'veterinarian__first_name', 'veterinarian__last_name',
    )[:5]

    # ADR p31: stock real en Product.stock_quantity (unidades base), no en Presentation.
    from django.db.models import F
    low_stock_qs = Product.objects.for_organization(org).filter(
        is_active=True, min_stock__gt=0, stock_quantity__lte=F('min_stock'),
    ).order_by('stock_quantity')
    low_stock = []
    for p in low_stock_qs:
        low_stock.append({
            'id': p.id,
            'name': p.name,
            'stock': str(p.stock_quantity),
            'min_stock': str(p.min_stock),
            'unit': p.get_base_unit_display(),
        })

    recent_list = []
    for r in recent_records:
        vet_name = f"{r['veterinarian__first_name'] or ''} {r['veterinarian__last_name'] or ''}".strip()
        recent_list.append({
            'id': r['id'],
            'pet_name': r['pet__name'],
            'diagnosis': r['diagnosis'],
            'created_at': r['created_at'],
            'veterinarian_name': vet_name,
        })

    return Response({
        'appointments_today': appointments_today,
        'recent_records': recent_list,
        'low_stock_products': low_stock,
        'low_stock_count': len(low_stock),
        'effective_timezone': org.timezone,
        'server_now_utc': now_utc,
        'local_today': today_local,
    })


# ===========================================================================
# Capa 5 — Daily series read endpoints (JSON-first; no frontend yet).
#
# Contract per user directive: every datapoint carries explicit `source` and
# `lifecycle_state`. snapshot rows come from DailyOrgMetrics; today is
# computed live via apps.analytics.services.compute_daily_metrics. corrupt
# rows are filtered out — surfaced via /api/internal/analytics-health/.
# ===========================================================================

# Hard cap per dashboard contract §5.1 (daily granularity).
MAX_RANGE_DAYS = 365
DEFAULT_RANGE_DAYS = 30

OPERATIONAL_FIELDS = (
    'appointments_total',
    'appointments_done',
    'appointments_no_show',
    'medical_records_closed',
)
FINANCIAL_FIELDS = (
    'revenue_paid',
    'revenue_accrual',
    'invoices_paid_count',
)
# Default values for missing-snapshot days. Money fields default to a Decimal
# so the JSON shape stays consistent across present / missing days
# (always serialized as string).
MISSING_DAY_DEFAULTS = {
    'appointments_total': 0,
    'appointments_done': 0,
    'appointments_no_show': 0,
    'medical_records_closed': 0,
    'revenue_paid': Decimal('0.00'),
    'revenue_accrual': Decimal('0.00'),
    'invoices_paid_count': 0,
}


def _parse_range(request, org, *, now=None):
    """Parse ?from / ?to / ?include_today. Returns (from_date, to_date,
    include_today) or raises ValueError with a human-readable message."""
    today = org_today_local(org, now=now)
    raw_to = request.query_params.get('to')
    raw_from = request.query_params.get('from')
    include_today = request.query_params.get('include_today', 'true').lower() != 'false'

    if raw_to:
        try:
            to_date = datetime.strptime(raw_to, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError("Invalid 'to' date; expected YYYY-MM-DD.")
    else:
        to_date = today

    if raw_from:
        try:
            from_date = datetime.strptime(raw_from, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError("Invalid 'from' date; expected YYYY-MM-DD.")
    else:
        from_date = to_date - timedelta(days=DEFAULT_RANGE_DAYS - 1)

    if from_date > to_date:
        raise ValueError("'from' must be <= 'to'.")
    days = (to_date - from_date).days + 1
    if days > MAX_RANGE_DAYS:
        raise ValueError(
            f"Range exceeds max {MAX_RANGE_DAYS} days for daily granularity."
        )
    return from_date, to_date, include_today


def _build_series(org, from_date, to_date, fields, include_today, *, now=None):
    """
    Build the series of (bucket_date → datapoint) for the given inclusive
    range. Snapshots fill historical days. Today is computed live (if
    requested AND today is within the range).
    """
    from apps.analytics.models import DailyOrgMetrics, LIFECYCLE_CORRUPT
    from apps.analytics.services import compute_daily_metrics

    today = org_today_local(org, now=now)

    # Pull all non-corrupt snapshots in range. Skip today (snapshots never
    # cover today by service rule).
    snapshot_rows = (
        DailyOrgMetrics.objects
        .for_organization(org)
        .filter(date__gte=from_date, date__lte=min(to_date, today - timedelta(days=1)))
        .exclude(lifecycle_state=LIFECYCLE_CORRUPT)
        .order_by('date')
    )
    snap_by_date = {row.date: row for row in snapshot_rows}

    series = []
    cursor = from_date
    while cursor <= to_date and cursor < today:
        snap = snap_by_date.get(cursor)
        if snap is None:
            # No snapshot built yet for this day. Surface as missing rather
            # than fake-zero, so the consumer can decide how to render.
            series.append({
                'bucket_date': cursor,
                'source': 'snapshot',
                'lifecycle_state': 'missing',
                'metrics_schema_version': None,
                'metrics': {f: MISSING_DAY_DEFAULTS[f] for f in fields},
            })
        else:
            series.append({
                'bucket_date': snap.date,
                'source': 'snapshot',
                'lifecycle_state': snap.lifecycle_state,
                'metrics_schema_version': snap.metrics_schema_version,
                'metrics': {f: getattr(snap, f) for f in fields},
            })
        cursor += timedelta(days=1)

    today_payload = None
    if include_today and from_date <= today <= to_date:
        live = compute_daily_metrics(org, today, now=now)
        today_payload = {
            'bucket_date': today,
            'source': 'live',
            'lifecycle_state': None,
            'metrics_schema_version': None,
            'metrics': {f: live[f] for f in fields},
        }

    # ADR p29 — dual-expose: agrega revenue_paid_net = gross + Σ MetricAdjustment.
    # Aditivo; el gross (revenue_paid) NO cambia. Los charts migran a net tras la
    # ventana de validación (kill-switch = seguir usando gross).
    if 'revenue_paid' in fields:
        _apply_revenue_net(org, from_date, to_date, series, today_payload)

    return series, today_payload


def _apply_revenue_net(org, from_date, to_date, series, today_payload):
    """
    Dual-window net of refunds (dashboard-metrics-contract §2.8, ADR p29).
    revenue_paid_net(day) = revenue_paid_gross(day) + Σ(MetricAdjustment.delta).
    Los snapshots frozen NO se reescriben — el ajuste vive en el día del evento.
    """
    from apps.analytics.models import MetricAdjustment

    rows = (
        MetricAdjustment.objects.for_organization(org)
        .filter(date__gte=from_date, date__lte=to_date, metric_name='revenue_paid')
        .values('date').annotate(total=Sum('delta'))
    )
    adj_by_date = {r['date']: (r['total'] or Decimal('0.00')) for r in rows}

    def _net(dp):
        gross = dp['metrics'].get('revenue_paid') or Decimal('0.00')
        delta = adj_by_date.get(dp['bucket_date'], Decimal('0.00'))
        dp['metrics']['revenue_paid_net'] = Decimal(gross) + delta

    for dp in series:
        _net(dp)
    if today_payload:
        _net(today_payload)


def _serialize_value(v):
    """Normalize Decimals to strings for JSON correctness (no float drift)."""
    if isinstance(v, Decimal):
        return str(v)
    return v


def _serialize_datapoint(dp):
    return {
        **dp,
        'bucket_date': dp['bucket_date'].isoformat(),
        'metrics': {k: _serialize_value(v) for k, v in dp['metrics'].items()},
    }


def _build_response(org, from_date, to_date, series, today, notes):
    return {
        'range': {
            'from': from_date.isoformat(),
            'to': to_date.isoformat(),
            'tz': str(get_context_timezone(org)),
        },
        'series': [_serialize_datapoint(dp) for dp in series],
        'today': _serialize_datapoint(today) if today else None,
        'notes': notes,
    }


def _series_endpoint(request, fields, permission_check):
    if request.user.organization is None:
        raise PermissionDenied("User has no organization assigned.")
    permission_check(request.user)
    now = timezone.now()
    try:
        from_date, to_date, include_today = _parse_range(
            request, request.user.organization, now=now,
        )
    except ValueError as exc:
        return Response(
            {'detail': str(exc),
             'meta': {'max_range_days': MAX_RANGE_DAYS}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    series, today_payload = _build_series(
        request.user.organization, from_date, to_date, fields, include_today,
        now=now,
    )

    notes = []
    missing_count = sum(1 for d in series if d['lifecycle_state'] == 'missing')
    if missing_count:
        notes.append(
            f"{missing_count} day(s) in range have no snapshot yet — they "
            "will populate after the next nightly build."
        )
    return Response(_build_response(
        request.user.organization, from_date, to_date, series, today_payload, notes,
    ))


@api_view(['GET'])
@permission_classes([make_permission('dashboard.view')])
def operations_series(request):
    """
    Operational daily series. Visible to ASSISTANT, VET, ADMIN.
    Reuses 'dashboard.view' permission for now (broad). Can split into
    'dashboard.operations.view' in a later sprint without breaking clients.
    """
    return _series_endpoint(
        request,
        fields=OPERATIONAL_FIELDS,
        permission_check=lambda user: None,  # already gated by HybridPermission
    )


def _require_admin_for_financial(user):
    """Financial series is ADMIN-only at the role layer (defense in depth
    on top of make_permission). Hard refuse for other roles."""
    if getattr(user, 'role', None) not in ('ADMIN', 'ADMIN_SAAS'):
        raise PermissionDenied(
            "Financial dashboard data is restricted to administrators."
        )


@api_view(['GET'])
@permission_classes([make_permission('dashboard.financial.view')])
def financial_series(request):
    """
    Financial daily series. Visible to ADMIN only.
    Permission code 'dashboard.financial.view' is granted to the ADMIN
    role via seed_permissions.
    """
    return _series_endpoint(
        request,
        fields=FINANCIAL_FIELDS,
        permission_check=_require_admin_for_financial,
    )


# ===========================================================================
# Capa 5 — Dashboard Summary (Hybrid Ops)
#
# Single endpoint that returns everything the operational dashboard needs:
# KPIs, timeline (30-min slots), waiting room, backlog, and stock alerts.
# Designed for <4 DB queries per request. Cached with org-prefixed keys.
# ===========================================================================

import json
from datetime import time as dt_time
from django.core.cache import cache
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

SUMMARY_CACHE_TTL = 30  # seconds — operational data, short TTL
SUMMARY_CACHE_PREFIX = 'dash:summary'


def _cache_key(org_id):
    return f'{SUMMARY_CACHE_PREFIX}:{org_id}'


@api_view(['GET'])
@permission_classes([make_permission('dashboard.summary')])
def dashboard_summary(request):
    """
    Operational dashboard payload — 100%% live point-in-time.

    /dashboard/summary/ does NOT currently expose temporal-bucketed KPIs
    (revenue, appointments, medical_records_closed). If temporal KPIs are
    added in the future, they MUST be delegated to
    apps.analytics.compute_daily_metrics.

    Point-in-time live aggregates currently exposed: in_progress_now,
    pending_today, low_stock_count, patients_today, ar_outstanding (ADMIN
    only), waiting_room, backlog, stock_alerts.

    This endpoint is NOT a source of truth for financial reporting or
    analytical queries. For audited or historical financial data, use:
      - /dashboard/financial/series/    (snapshots + today via analytics)
      - /dashboard/operations/series/   (idem)

    Adding new KPIs to this endpoint that are NOT pre-declared as live-only
    in dashboard-metrics-contract.md §3 requires an ADR.
    """
    user = request.user
    org = user.organization
    if org is None:
        raise PermissionDenied("User has no organization assigned.")

    cached = cache.get(_cache_key(org.id))
    if cached is not None:
        return Response(cached)

    today_local = org_today_local(org)
    today_bounds = local_day_bounds_utc(org, today_local)
    now_utc = org_now_utc(org)

    # ---- Query 1: Today's appointments ----
    appointments = list(
        Appointment.objects
        .for_organization(org)
        .filter(
            start_datetime__gte=today_bounds[0],
            start_datetime__lt=today_bounds[1],
        )
        .select_related('pet', 'veterinarian', 'pet__owner')
        .order_by('start_datetime')
    )

    # ---- Query 2: Low stock (ADR p31) ----
    # El stock real vive en Product.stock_quantity (unidades base). Presentation.stock
    # quedó congelado tras la migración 0018 — leerlo daba 0 falsos. La alerta es
    # por producto. Requiere min_stock > 0: sin umbral configurado no hay punto de
    # reorden y un producto recién creado (stock 0, ADR p33) no debe inundar la tarjeta.
    from apps.inventory.models import Product
    low_stock_products = list(
        Product.objects
        .for_organization(org)
        .filter(is_active=True, min_stock__gt=0, stock_quantity__lte=F('min_stock'))
        .order_by('stock_quantity')[:5]
    )

    # ---- Query 3: Backlog ----
    open_qs = MedicalRecord.objects.for_organization(org).filter(status='open')
    attention_cutoff = now_utc - timedelta(hours=3)
    backlog_agg = open_qs.aggregate(
        total=Count('id'),
        needs_attention_count=Count(
            'id',
            filter=Q(created_at__lt=attention_cutoff) &
                    (Q(diagnosis__isnull=True) | Q(diagnosis='')),
        ),
        without_diagnosis=Count(
            'id',
            filter=Q(diagnosis__isnull=True) | Q(diagnosis=''),
        ),
    )

    open_records = []
    for mr in open_qs.select_related('pet', 'veterinarian').order_by('created_at')[:50]:
        elapsed = now_utc - mr.created_at
        hours_open = elapsed.total_seconds() / 3600
        has_diag = bool(mr.diagnosis and mr.diagnosis.strip())
        open_records.append({
            'public_id': str(mr.public_id),
            'pet_name': mr.pet.name if mr.pet else None,
            'veterinarian_name': (
                f"{mr.veterinarian.first_name} {mr.veterinarian.last_name}".strip()
                if mr.veterinarian else None
            ),
            'days_open': round(hours_open / 24, 1),
            'hours_open': round(hours_open, 1),
            'has_diagnosis': has_diag,
            'needs_attention': (not has_diag and elapsed > timedelta(hours=3)),
        })

    # ---- Query 4: AR outstanding (ADMIN only) ----
    is_admin = getattr(user, 'role', None) in ('ADMIN', 'ADMIN_SAAS')
    ar_outstanding = None
    if is_admin:
        from apps.billing.models import Invoice
        ar_outstanding = str(
            Invoice.objects
            .for_organization(org)
            .filter(status='posted')
            .aggregate(total=Coalesce(Sum('total'), Decimal('0.00')))['total']
            .quantize(Decimal('0.01'))
        )

    # ---- Build KPIs ----
    kpis = {
        'in_progress_now': sum(1 for a in appointments if a.status == 'in_progress'),
        'pending_today': sum(
            1 for a in appointments
            if a.status in ('scheduled', 'confirmed')
        ),
        'low_stock_count': len(low_stock_products),
        'patients_today': len(
            set(a.pet_id for a in appointments if a.pet_id is not None)
        ),
    }
    if is_admin:
        kpis['ar_outstanding'] = ar_outstanding

    # ---- Build Timeline (30-min slots) ----
    slots = _build_timeline_slots(appointments, org)

    # ---- Build Waiting Room ----
    waiting_room = _build_waiting_room(appointments, now_utc, org)

    # ---- Build Backlog ----
    backlog = {
        'open_total': backlog_agg['total'],
        'returned_records': len(open_records),
        'needs_attention_count': backlog_agg['needs_attention_count'],
        'without_diagnosis': backlog_agg['without_diagnosis'],
        'open_records': open_records,
    }

    # ---- Build Stock Alerts (por producto — stock product-level, ADR p31) ----
    stock_alerts = []
    for p in low_stock_products:
        stock_alerts.append({
            'product_name': p.name,
            'stock': str(p.stock_quantity),
            'min_stock': str(p.min_stock),
            'unit': p.get_base_unit_display(),
            'severity': 'critical' if p.stock_quantity == 0 else 'warning',
        })

    payload = {
        'metrics_schema_version': METRICS_SCHEMA_VERSION,
        'source': 'live_summary',
        'kpis': kpis,
        'timeline': slots,
        'waiting_room': waiting_room,
        'backlog': backlog,
        'stock_alerts': stock_alerts,
        'effective_timezone': org.timezone,
        'local_today': today_local.isoformat(),
    }

    cache.set(_cache_key(org.id), payload, SUMMARY_CACHE_TTL)
    return Response(payload)


# ===========================================================================
# Activación de la clínica (primer uso / SetupChecklist)
# ===========================================================================

@api_view(['GET'])
@permission_classes([make_permission('dashboard.summary')])
def dashboard_activation(request):
    """
    Estado de activación de la clínica — read-only, multi-tenant, SIN flags.

    Devuelve la EXISTENCIA real (de por vida) de los hitos de arranque para que el
    FirstRunAssistant del dashboard se derive de datos reales y NO de un flag
    persistido por usuario.

    - has_patients:        ≥1 Pet NO genérico (la mascota genérica se siembra al crear
                           la org; no cuenta como "tiene pacientes").
    - has_clinic_contact:  Organization.phone capturado.
    - has_services:        ≥1 Service.
    - has_appointments:    ≥1 Appointment (informativo).
    - has_consultations:   ≥1 MedicalRecord (informativo).

    `completed` = clínica LISTA PARA OPERAR = has_patients AND has_clinic_contact
    AND has_services (readiness).
    Deliberadamente NO depende de has_appointments/has_consultations: esos hitos
    dependen de que llegue un cliente real, y mantendrían el onboarding activo durante
    días aunque la clínica ya esté configurada. El onboarding mide "lista para empezar",
    no "ya usó el sistema" → se completa en la primera sesión (3-5 min).
    has_appointments/has_consultations se siguen devolviendo (informativos) pero NO
    gatean el cierre del onboarding. No escribe nada.

    Sobre `has_clinic_contact` — por qué `bool(phone)` basta y por qué el HORARIO
    no es un hito:
      - `Organization.phone` NACE vacío y `OrganizationSerializer.validate_phone`
        (regla en `apps.core.validators`) impide guardar basura → *existir*
        equivale a *ser válido*. La señal sigue siendo existencia real, sin flags.
      - El horario NO es derivable: `create_default_schedule` siembra las 7 filas al
        crear la org, así que "tiene horario" es True desde el segundo cero.
        Distinguir "es el default" de "la clínica lo revisó" exigiría un flag o un
        timestamp — exactamente lo que este endpoint prohíbe. Por eso el horario se
        edita dentro del paso pero NO gatea (ver plan de onboarding §3.2/§8).

    Imports locales para evitar acoplar el módulo dashboard al cargar (idiomático
    en este archivo — read-only sobre los dominios).
    """
    from apps.patients.models import Pet
    from apps.billing.models import Service

    org = request.user.organization
    if not org:
        raise PermissionDenied("User has no organization assigned")

    has_patients = Pet.objects.for_organization(org).filter(is_generic=False).exists()
    has_clinic_contact = bool((org.phone or '').strip())
    has_services = Service.objects.for_organization(org).exists()
    has_appointments = Appointment.objects.for_organization(org).exists()
    has_consultations = MedicalRecord.objects.for_organization(org).exists()

    return Response({
        'has_patients': has_patients,
        'has_clinic_contact': has_clinic_contact,
        'has_services': has_services,
        'has_appointments': has_appointments,
        'has_consultations': has_consultations,
        # Readiness: paciente + contacto + servicio. NO depende de cita/consulta
        # (eventos externos, requieren que llegue un cliente real).
        'completed': has_patients and has_clinic_contact and has_services,
    })


# ---- Timeline builder ----

# Default clinic hours if no appointments exist for the day.
_DEFAULT_OPEN_TIME = dt_time(8, 0)
_DEFAULT_CLOSE_TIME = dt_time(20, 0)
_SLOT_MINUTES = 30


def _serialize_timeline_appt(appt, tz):
    """Single appointment payload for a timeline slot.

    species/breed añadidos para la vista de lista (TodayAgendaList). Pet.species
    es CharField libre y Pet.breed puede ser '' → se normaliza a None.
    """
    pet = appt.pet
    return {
        'time': appt.start_datetime.astimezone(tz).strftime('%H:%M'),
        'public_id': str(appt.public_id) if getattr(appt, 'public_id', None) else str(appt.pk),
        'pet_name': pet.name if pet else None,
        'pet_is_generic': pet.is_generic if pet else False,
        'species': pet.species if pet else None,
        'breed': (pet.breed or None) if pet else None,
        'owner_name': pet.owner.name if pet and pet.owner else None,
        'veterinarian_name': (
            f"{appt.veterinarian.first_name} {appt.veterinarian.last_name}".strip()
            if appt.veterinarian else None
        ),
        'reason': appt.reason,
        'status': appt.status,
        'walk_in': getattr(appt, 'walk_in', False),
    }


def _build_timeline_slots(appointments, org):
    tz = get_context_timezone(org)

    if appointments:
        first = min(a.start_datetime for a in appointments)
        last = max(a.start_datetime for a in appointments)
        first_local = first.astimezone(tz)
        last_local = last.astimezone(tz)
        # Floor to previous 30-min mark
        open_minutes = (first_local.hour * 60 + first_local.minute) // _SLOT_MINUTES * _SLOT_MINUTES
        close_minutes = ((last_local.hour * 60 + last_local.minute) // _SLOT_MINUTES + 1) * _SLOT_MINUTES
        day = first_local.date()
        open_time = dt_time(open_minutes // 60, open_minutes % 60)
        if close_minutes >= 24 * 60:
            close_time = dt_time(23, 59)
        else:
            close_time = dt_time(close_minutes // 60, close_minutes % 60)
    else:
        day = org_today_local(org)
        open_time = _DEFAULT_OPEN_TIME
        close_time = _DEFAULT_CLOSE_TIME

    # Build slot grid
    slots = []
    cursor_minutes = open_time.hour * 60 + open_time.minute
    end_minutes = close_time.hour * 60 + close_time.minute

    while cursor_minutes < end_minutes:
        slot_hour = cursor_minutes // 60
        slot_min = cursor_minutes % 60
        slot_time = dt_time(slot_hour, slot_min)

        # Find appointments that fall into this 30-min window
        slot_start_utc = datetime.combine(day, slot_time).replace(tzinfo=tz).astimezone(ZoneInfo('UTC'))
        slot_end_utc = slot_start_utc + timedelta(minutes=_SLOT_MINUTES)

        slot_appts = [
            a for a in appointments
            if slot_start_utc <= a.start_datetime < slot_end_utc
        ]

        if slot_appts:
            appts_data = [_serialize_timeline_appt(a, tz) for a in slot_appts]
            # 'appointment' (singular) = primera cita: alias legacy para no romper
            # consumidores previos. 'appointments' (plural) = todas las del bucket,
            # evita pérdida de citas en la misma franja de 30 min (TodayAgendaList).
            slot_data = appts_data[0]
        else:
            appts_data = []
            slot_data = None

        slots.append({
            'time': slot_time.strftime('%H:%M'),
            'appointment': slot_data,
            'appointments': appts_data,
        })
        cursor_minutes += _SLOT_MINUTES

    return slots


def _build_waiting_room(appointments, now_utc, org):
    tz = get_context_timezone(org)
    items = []

    for appt in appointments:
        if appt.status not in ('scheduled', 'confirmed'):
            continue
        # Only include appointments whose start time is within [-30min, +60min] of now
        # or already past (patient is here waiting)
        local_start = appt.start_datetime.astimezone(tz)
        wait_minutes = (now_utc - appt.start_datetime).total_seconds() / 60

        # Show: starting within next 60 min, or already past (waiting) up to 30 min early arrival
        if -30 <= wait_minutes <= 60:
            items.append({
                'pet_name': appt.pet.name if appt.pet else None,
                'time': local_start.strftime('%H:%M'),
                'owner_name': appt.pet.owner.name if appt.pet and appt.pet.owner else None,
                'status': appt.status,
                'wait_minutes': max(0, int(wait_minutes)) if wait_minutes > 0 else 0,
                'is_late': wait_minutes > 30,
            })

    # Sort by wait time descending (longest waiting first)
    items.sort(key=lambda x: x['wait_minutes'], reverse=True)
    return items[:3]


# Need ZoneInfo for UTC conversion in timeline builder
from zoneinfo import ZoneInfo
