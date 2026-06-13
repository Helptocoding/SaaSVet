"""
apps/cash — Turno de caja y cierre Z (ADR p28).

Reconciliación del cajón físico: agregado sobre el ledger de `Payment` (billing).
Boundary separado de billing (bounded context distinto). `Payment.cash_session`
es FK con string ref → dependencia unidireccional billing→cash, sin ciclo.
"""
import logging
from decimal import Decimal

from django.db import models

from apps.core.models import OrganizationalModel, PublicIdMixin

logger = logging.getLogger(__name__)


class CashSession(PublicIdMixin, OrganizationalModel):
    """
    Turno de caja. Modelo público (URLs por public_id; reportes Z se llavean por
    public_id, NO por user — prepara v2 Register/Terminal, DD-004).

    Lifecycle: open → closed (terminal). `force_closed` = cierre administrativo.
    Inmutable tras cerrar: expected/counted/difference/closed_snapshot.

    El `closed_snapshot` (JSON) es el **Z legal congelado** — no se reinterpreta
    si cambia el código de reporting (versionado por `report_schema_version`,
    mismo principio que DailyOrgMetrics frozen + metrics_schema_version).

    `closed_at` es un anchor con CHECK constraint (mismo patrón que ADR p9):
    status cerrado ⇒ closed_at NOT NULL.

    Pertenencia v1: una sesión abierta por (organization, opened_by). El writer
    autoritativo de open/close vive en cash/services.py.
    """
    STATUS_CHOICES = (
        ('open', 'Abierta'),
        ('closed', 'Cerrada'),
        ('force_closed', 'Cerrada administrativamente'),
    )

    opened_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_sessions_opened',
    )
    opened_at = models.DateTimeField()
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='open')

    closed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_sessions_closed',
    )
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    difference = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    # Z legal congelado al cierre + su versión de schema (DD-003).
    closed_snapshot = models.JSONField(null=True, blank=True)
    report_schema_version = models.PositiveSmallIntegerField(default=1)
    # organization, created_at, updated_at, created_by, updated_by, is_active
    # heredados de OrganizationalModel.

    def __str__(self):
        return f"CashSession #{self.pk} [{self.status}]"

    class Meta:
        ordering = ['-opened_at', '-id']
        indexes = [
            models.Index(fields=['organization', 'status']),
        ]
        constraints = [
            # Anchor invariant (espejo ADR p9): cerrada ⇒ closed_at presente.
            models.CheckConstraint(
                condition=(
                    ~models.Q(status__in=['closed', 'force_closed'])
                    | models.Q(closed_at__isnull=False)
                ),
                name='cashsession_closed_requires_closed_at',
            ),
            models.CheckConstraint(
                condition=models.Q(opening_float__gte=0),
                name='cashsession_opening_float_non_negative',
            ),
            # Una sola caja abierta por usuario/org (resuelve doble-apertura).
            models.UniqueConstraint(
                fields=['organization', 'opened_by'],
                condition=models.Q(status='open'),
                name='cashsession_one_open_per_user',
            ),
        ]


class CashMovement(PublicIdMixin, OrganizationalModel):
    """
    Movimiento manual de efectivo del cajón (ADR p39): entrada, retiro o gasto
    dentro de un turno abierto. Sin esto, un retiro a banco a mitad de turno
    producía un faltante falso en el cierre Z.

    Append-only (invariante #3 del sistema): sin PATCH/DELETE; una corrección
    se registra como contra-movimiento. `amount > 0` siempre — el signo lo da
    `movement_type` (invariante #4). Solo efectivo por definición (es el cajón
    físico); card/transfer no tienen movimientos manuales.

    Writer único: cash/services.register_cash_movement (lock de CashSession,
    cabeza del orden global → serializado contra el cierre Z; ningún movimiento
    se cuela después del conteo).
    """
    TYPE_CHOICES = (
        ('deposit', 'Entrada manual'),
        ('withdrawal', 'Retiro de efectivo'),
        ('expense', 'Gasto'),
    )

    cash_session = models.ForeignKey(
        CashSession, on_delete=models.PROTECT, related_name='movements',
    )
    movement_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    occurred_at = models.DateTimeField(editable=False)
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_movements',
    )

    def __str__(self):
        return f"CashMovement #{self.pk} [{self.movement_type}] ${self.amount}"

    class Meta:
        ordering = ['-occurred_at', '-id']
        indexes = [
            models.Index(fields=['organization', 'cash_session']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='cashmovement_amount_positive',
            ),
        ]
