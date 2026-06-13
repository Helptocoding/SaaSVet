import logging
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.db.models import Q, Sum
from django.utils import timezone
from apps.core.models import OrganizationalModel, PublicIdMixin
from apps.billing.money import discount_amount, invoice_totals, line_subtotal, money

logger = logging.getLogger(__name__)


class Service(PublicIdMixin, OrganizationalModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    # is_active, created_at, updated_at heredados de OrganizationalModel

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(base_price__gt=0),
                name='service_base_price_positive',
            ),
        ]


class Invoice(PublicIdMixin, OrganizationalModel):
    STATUS_CHOICES = (
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmada'),
        ('paid', 'Pagada'),
        ('cancelled', 'Cancelada'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('cash', 'Efectivo'),
        ('card', 'Tarjeta'),
        ('transfer', 'Transferencia'),
        ('other', 'Otro'),
    )
    INVOICE_TYPE_CHOICES = (
        ('consultation', 'Consulta médica'),
        ('direct_sale', 'Venta directa'),
    )

    invoice_type = models.CharField(
        max_length=20,
        choices=INVOICE_TYPE_CHOICES,
        default='consultation',
    )
    medical_record = models.OneToOneField(
        'medical_records.MedicalRecord',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice',
    )
    appointment = models.OneToOneField(
        'appointments.Appointment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice'
    )
    owner = models.ForeignKey(
        'patients.Owner',
        on_delete=models.PROTECT,
        related_name='invoices'
    )
    pet = models.ForeignKey(
        'patients.Pet',
        on_delete=models.PROTECT,
        related_name='invoices',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices_created'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        null=True,
        blank=True
    )

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    notes = models.TextField(blank=True)

    # ------------------------------------------------------------------
    # Analytics anchors (editable=False; solo escritos por billing/services.py).
    # Cualquier mutación fuera de los services rompe el contrato analítico
    # (ver docs/dashboard-metrics-contract.md §2.7).
    # ------------------------------------------------------------------
    paid_at = models.DateTimeField(null=True, blank=True, editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)

    # Provenance del anchor: permite excluir / auditar / recomputar rows
    # con anchor backfilled. Nuevos writes via service registran 'service'.
    ANCHOR_SOURCE_CHOICES = (
        ('service', 'Service writer'),
        ('audit_log', 'Backfilled from InvoiceAuditLog timestamp'),
        ('fallback', 'Backfilled from updated_at / created_at fallback'),
        ('unresolved', 'No reliable source — anchor left NULL'),
        ('legacy', 'Existed before provenance tracking was introduced'),
    )
    paid_at_source = models.CharField(
        max_length=24, choices=ANCHOR_SOURCE_CHOICES,
        default='service', editable=False,
    )
    confirmed_at_source = models.CharField(
        max_length=24, choices=ANCHOR_SOURCE_CHOICES,
        default='service', editable=False,
    )
    cancelled_at_source = models.CharField(
        max_length=24, choices=ANCHOR_SOURCE_CHOICES,
        default='service', editable=False,
    )
    # created_at, updated_at heredados de OrganizationalModel

    def clean(self):
        org = self.organization_id
        if org and self.owner_id and self.owner.organization_id != org:
            raise ValidationError("El propietario no pertenece a la misma organizacion que la factura.")
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organizacion que la factura.")
        if org and self.appointment_id and self.appointment.organization_id != org:
            raise ValidationError("La cita no pertenece a la misma organizacion que la factura.")
        if org and self.medical_record_id and self.medical_record.organization_id != org:
            raise ValidationError("El registro medico no pertenece a la misma organizacion que la factura.")

    def recalculate_totals(self):
        # ⚠️ all_objects: bypasses tenant filter — necesario porque este método
        # puede correr desde InvoiceItem.save() cuando el contexto ya fue limpiado
        # (ej. señales post_save). Do NOT replace with objects.
        # Suma vía agregado SQL: no itera ni instancia filas en Python. recalc
        # se llama una vez por InvoiceItem.save(); evita O(n) objetos por llamada.
        raw_subtotal = (
            InvoiceItem.all_objects
            .filter(invoice=self, is_active=True)
            .aggregate(s=Sum('subtotal'))['s']
        ) or Decimal('0.00')
        subtotal, tax_amount, total = invoice_totals(raw_subtotal, self.tax_rate)
        # updated_at explícito: .update() bypasea auto_now y dejaría el timestamp
        # stale tras editar ítems de un draft.
        Invoice.all_objects.filter(pk=self.pk).update(
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
            updated_at=timezone.now(),
        )

    @property
    def remaining_balance(self):
        """
        Saldo de cobranza (financial-event-model-contract §8.1):
            remaining_balance = total − Σ(Payment.amount)
        Invariante financiero real: status='paid' ⟺ remaining_balance == 0.
        Los refunds NO entran aquí (§8.2) — operan post-liquidación vía nota de
        crédito y no reabren la cobranza. Propiedad computada en v1 (DD-001).
        """
        paid = self.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        return self.total - paid

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
            # Capa 3 — analytics anchors. Soportan cash-basis snapshot,
            # accrual snapshot, AR aging, cancellation count.
            # Ver docs/analytics-schema-audit.md §2.6.
            models.Index(fields=["organization", "status", "paid_at"],
                         name="idx_inv_org_status_paid"),
            models.Index(fields=["organization", "status", "confirmed_at"],
                         name="idx_inv_org_status_conf"),
            models.Index(fields=["organization", "status", "cancelled_at"],
                         name="idx_inv_org_status_canc"),
            # P1-2: listado paginado de Cobros ordena por (-created_at, -id)
            # filtrando por org sin status. Sin este índice, PageNumber sobre
            # 25k+ facturas haría sort en memoria.
            models.Index(fields=["organization", "-created_at", "-id"],
                         name="idx_invoice_org_created_id"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tax_rate__gte=0) & models.Q(tax_rate__lte=1),
                name="invoice_tax_rate_range",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0),
                name="invoice_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total__gte=models.F('subtotal')),
                name="invoice_total_gte_subtotal",
            ),
            # Event-authority invariants (analytics). Bloquean writes vía
            # queryset.update() / bulk_update / admin / raw SQL que dejarían
            # anchors NULL para estados que requieren timestamp explícito.
            # Ver docs/analytics-schema-audit.md §2.15 + §2.3 + §2.4.
            models.CheckConstraint(
                condition=~models.Q(status='paid') | models.Q(paid_at__isnull=False),
                name="invoice_paid_status_requires_paid_at",
            ),
            models.CheckConstraint(
                condition=~models.Q(status__in=['confirmed', 'paid']) | models.Q(confirmed_at__isnull=False),
                name="invoice_confirmed_status_requires_confirmed_at",
            ),
            models.CheckConstraint(
                condition=~models.Q(status='cancelled') | models.Q(cancelled_at__isnull=False),
                name="invoice_cancelled_status_requires_cancelled_at",
            ),
        ]


class InvoiceItem(OrganizationalModel):
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items'
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_items'
    )
    presentation = models.ForeignKey(
        'inventory.Presentation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='invoice_items',
    )
    # TODO (v2):
    # Hacer 'presentation' obligatorio a nivel DB (null=False)
    # cuando todos los flujos, seeds y frontend estén completamente migrados.

    # ADR p30: ítem agregado al cobro de la consulta al dispensar un producto de
    # la receta interna que el cliente decide llevar. NO se crea una factura
    # aparte: la línea va en la MISMA factura de consulta. Doble función:
    #   1) Provenance: qué línea de receta (PrescriptionItem) surtió esta línea.
    #   2) Discriminador del descuento de stock: en una factura `consultation`,
    #      los ítems sincronizados desde MedicalRecordProduct YA descontaron stock
    #      al consumirse en consulta; estos ítems dispensados NO. La única ruta de
    #      descuento (_confirm_locked_invoice) usa este FK para saber qué ítems de
    #      una consulta liquidan stock al confirmar. En `direct_sale` se ignora
    #      (todos los ítems liquidan). La Prescription interna es el respaldo legal
    #      del producto requires_prescription (no se exige atestación externa,
    #      ADR p26); el permiso billing.rx_dispense se valida en la view.
    dispensed_from_prescription_item = models.ForeignKey(
        'prescriptions.PrescriptionItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dispensed_invoice_items',
    )
    DISCOUNT_TYPE_CHOICES = (
        ('percentage', 'Porcentaje'),
        ('fixed', 'Monto fijo'),
    )

    discount_type = models.CharField(
        max_length=10,
        choices=DISCOUNT_TYPE_CHOICES,
        null=True,
        blank=True,
    )

    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Monto o porcentaje del descuento. 0 = sin descuento."
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def _warn_if_not_atomic(self, op):
        # Guard de observabilidad (NO bloqueante). Toda mutación concurrente de
        # InvoiceItem debe correr dentro de transaction.atomic() con la Invoice
        # lockeada (select_for_update) para que recalculate_totals no sufra
        # lost-update — ver "Orden global de locks" en CLAUDE.md.
        #
        # Es WARNING y no assert (a diferencia de MedicalRecordProduct.save):
        # InvoiceItem.save() no toma lock interno, solo recalcula vía un UPDATE
        # atómico único. Un create puntual en autocommit (admin, shell, seeds,
        # setUp de TransactionTestCase) es seguro y legítimo; un assert duro los
        # rompería. El warning solo señala mutaciones fuera de atomic para que
        # monitoring detecte un caller concurrente nuevo que rompa el contrato.
        if not connection.in_atomic_block:
            logger.warning(
                "INVOICEITEM_MUTATION_OUTSIDE_ATOMIC",
                extra={
                    'event': 'INVOICEITEM_MUTATION_OUTSIDE_ATOMIC',
                    'op': op,
                    'invoice_id': self.invoice_id,
                    'invoice_item_pk': self.pk,
                },
            )

    def save(self, *args, **kwargs):
        # Hereda organization del invoice — sin query extra
        if self.invoice_id and not self.organization_id:
            self.organization_id = self.invoice.organization_id

        self._warn_if_not_atomic('save')

        gross = money(self.quantity * self.unit_price)
        disc = discount_amount(gross, self.discount_type, self.discount_value)
        self.subtotal = line_subtotal(self.quantity, self.unit_price, disc)

        super().save(*args, **kwargs)
        self.invoice.recalculate_totals()

    def delete(self, *args, **kwargs):
        self._warn_if_not_atomic('delete')
        invoice = self.invoice
        super().delete(*args, **kwargs)
        invoice.recalculate_totals()

    class Meta:
        unique_together = [('invoice', 'presentation')]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="invoiceitem_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="invoiceitem_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0),
                name="invoiceitem_subtotal_non_negative",
            ),
            # XOR: exactamente uno de service o presentation debe estar presente
            models.CheckConstraint(
                condition=(
                    (Q(service__isnull=False) & Q(presentation__isnull=True)) |
                    (Q(service__isnull=True)  & Q(presentation__isnull=False))
                ),
                name="invoiceitem_exactly_one_source",
            ),
            # Un mismo servicio no puede aparecer dos veces en la misma factura
            models.UniqueConstraint(
                fields=['invoice', 'service'],
                condition=Q(service__isnull=False),
                name='invoiceitem_unique_invoice_service',
            ),
        ]


class InvoiceAuditLog(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='audit_logs')
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class Payment(OrganizationalModel):
    """
    Evento financiero append-only: dinero recibido del cliente (signo +inflow).

    Contrato: docs/financial-event-model-contract.md
      §2 campos canónicos · §3 invariantes · §5 signo · §7 fully_allocated (v1).
    ADR p27. Modelo INTERNO (PK-only): NO expone public_id (ADR p18/p24).

    Append-only: sin PATCH/DELETE. `amount` y `occurred_at` inmutables tras
    la creación. Las correcciones son contra-asientos (RefundPayment /
    RefundReversal, ADR p29), nunca mutaciones.

    NOTA: el campo `cash_session` (FK a cash.CashSession) lo agrega ADR p28.
    """
    METHOD_CHOICES = (
        ('cash', 'Efectivo'),
        ('card', 'Tarjeta'),
        ('transfer', 'Transferencia'),
        ('other', 'Otro'),
    )
    PROVENANCE_CHOICES = (
        ('service', 'Service writer'),
        ('legacy', 'Backfilled desde Invoice.payment_method'),
    )

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    # Momento financiero real — NO created_at/paid_at. En backfill = Invoice.paid_at.
    occurred_at = models.DateTimeField()
    # Responsable del movimiento — server-side (request.user). SET_NULL: los
    # usuarios se desactivan, no se borran. NULL en backfill legacy.
    actor = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments_made',
    )
    reference = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)
    provenance = models.CharField(
        max_length=20, choices=PROVENANCE_CHOICES, default='service',
    )
    # ADR p28: turno de caja. String ref → dependencia unidireccional billing→cash
    # sin ciclo de import. PROTECT: no se borra una sesión con pagos. Nullable:
    # NULL cuando require_open_cash_session está apagado (default).
    cash_session = models.ForeignKey(
        'cash.CashSession',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='payments',
    )
    # organization, created_at, updated_at, created_by, updated_by, is_active
    # heredados de OrganizationalModel.

    def __str__(self):
        return f"Payment #{self.pk} — {self.amount} ({self.method})"

    class Meta:
        ordering = ['occurred_at', 'id']
        indexes = [
            models.Index(fields=['organization', 'invoice']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='payment_amount_positive',
            ),
            # Idempotencia (contrato §9): único por org cuando hay key.
            models.UniqueConstraint(
                fields=['organization', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='payment_unique_idempotency_key_per_org',
            ),
        ]


class ExternalPrescriptionAttestation(PublicIdMixin, OrganizationalModel):
    """
    Atestación de receta externa para dispensar un producto `requires_prescription`
    en una venta directa (ADR p26). Registro legal append-only — sin PATCH/DELETE.

    NO reemplaza la receta clínica interna (`prescriptions.Prescription`, OneToOne a
    consulta). Esto es un evento de retail: el cliente presentó una receta externa
    válida. Mantenerlos separados evita basura clínica (contamina prescriptions_issued).

    Retención: documento regulatorio (NOM medicamentos controlados) — sin borrado.
    `prescriber_name` es PII de tercero (LFPDPPP): base lícita = obligación de
    dispensación; retención acotada a esa obligación. Archival/WORM futuro = DD-005.
    """
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name='rx_attestations',
    )
    presentation = models.ForeignKey(
        'inventory.Presentation', on_delete=models.PROTECT,
        related_name='rx_attestations',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    # Responsable de autorizar la dispensación — server-side (request.user).
    attested_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rx_attestations',
    )
    attested_at = models.DateTimeField(auto_now_add=True)  # momento de la atestación
    prescriber_name = models.CharField(max_length=255)
    prescription_folio = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    # organization, created_at, updated_at, ... heredados de OrganizationalModel.

    def __str__(self):
        return f"RxAttestation #{self.pk} — inv {self.invoice_id}"

    class Meta:
        ordering = ['-attested_at', '-id']
        indexes = [
            models.Index(fields=['organization', 'invoice']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='rxattestation_quantity_positive',
            ),
        ]


# Causa tipificada de una nota de crédito (ADR p29). Constante app-level (estilo
# SPECIES_CHOICES): sin `choices=` en el campo → agregar un código no requiere
# migración, pero la lista es estable/queryable para conciliación/SAT/fraude.
CREDIT_NOTE_REASON_CODES = [
    'customer_return', 'damaged_product', 'expired_product', 'duplicate_charge',
    'pricing_error', 'goodwill', 'clinical_cancellation', 'other',
]


class CreditNote(PublicIdMixin, OrganizationalModel):
    """
    Nota de crédito (devolución post-pago) — ADR p29. Documento legal append-only.

    NO reabre la factura original (permanece `paid`, contrato §8.2). El neto de
    revenue se computa en read-time vía `analytics.MetricAdjustment`, jamás
    editando la factura. `issued_at` es anchor (provenance + CHECK, patrón ADR p9).
    """
    STATUS_CHOICES = (('issued', 'Emitida'),)

    original_invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name='credit_notes',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='issued')
    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='credit_notes_created',
    )
    issued_at = models.DateTimeField(null=True, blank=True, editable=False)
    issued_at_source = models.CharField(
        max_length=24, choices=Invoice.ANCHOR_SOURCE_CHOICES,
        default='service', editable=False,
    )
    total_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reason_code = models.CharField(max_length=40)
    reason_notes = models.TextField(blank=True)

    def __str__(self):
        return f"CreditNote #{self.pk} ← inv {self.original_invoice_id}"

    class Meta:
        ordering = ['-issued_at', '-id']
        indexes = [models.Index(fields=['organization', 'original_invoice'])]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status='issued') | models.Q(issued_at__isnull=False),
                name='creditnote_issued_requires_issued_at',
            ),
            models.CheckConstraint(
                condition=models.Q(total_refunded__gte=0),
                name='creditnote_total_refunded_non_negative',
            ),
        ]


class CreditNoteItem(OrganizationalModel):
    """Línea devuelta de una nota de crédito. Interna (PK-only)."""
    DISPOSITION_CHOICES = (
        ('restock', 'Reingresa a stock'),
        ('discard', 'Descartado (abierto/usado)'),
    )

    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name='items')
    invoice_item = models.ForeignKey(
        InvoiceItem, on_delete=models.PROTECT, related_name='credit_note_items',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    disposition = models.CharField(max_length=16, choices=DISPOSITION_CHOICES, default='restock')

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='creditnoteitem_quantity_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name='creditnoteitem_amount_non_negative',
            ),
        ]


class RefundPayment(OrganizationalModel):
    """
    Evento financiero: dinero devuelto al cliente (signo − inflow→outflow).
    Append-only. Campos canónicos del contrato §2 (mismos nombres que Payment).
    """
    credit_note = models.ForeignKey(CreditNote, on_delete=models.PROTECT, related_name='refund_payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES)
    occurred_at = models.DateTimeField()
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='refunds_made',
    )
    cash_session = models.ForeignKey(
        'cash.CashSession', on_delete=models.PROTECT, null=True, blank=True,
        related_name='refund_payments',
    )
    reference = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)
    provenance = models.CharField(max_length=20, choices=Payment.PROVENANCE_CHOICES, default='service')

    def __str__(self):
        return f"RefundPayment #{self.pk} — {self.amount} ({self.method})"

    class Meta:
        ordering = ['occurred_at', 'id']
        indexes = [models.Index(fields=['organization', 'credit_note'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='refundpayment_amount_positive',
            ),
            models.UniqueConstraint(
                fields=['organization', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='refundpayment_unique_idempotency_key_per_org',
            ),
        ]


class RefundReversal(OrganizationalModel):
    """
    Contra-asiento de un `RefundPayment` emitido por error (contrato §6).
    Append-only — NO es void/edit. Invariante: ≤1 reversal por refund; un reversal
    no es reversible (la corrección es un nuevo RefundPayment).
    """
    reverses = models.ForeignKey(RefundPayment, on_delete=models.PROTECT, related_name='reversals')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES)
    occurred_at = models.DateTimeField()
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='refund_reversals_made',
    )
    cash_session = models.ForeignKey(
        'cash.CashSession', on_delete=models.PROTECT, null=True, blank=True,
        related_name='refund_reversals',
    )
    reference = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)
    provenance = models.CharField(max_length=20, choices=Payment.PROVENANCE_CHOICES, default='service')
    reason_code = models.CharField(max_length=40, blank=True)
    reason_notes = models.TextField(blank=True)

    def __str__(self):
        return f"RefundReversal #{self.pk} ↺ refund {self.reverses_id}"

    class Meta:
        ordering = ['occurred_at', 'id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='refundreversal_amount_positive',
            ),
            # ≤1 reversal por refund (contrato §6).
            models.UniqueConstraint(
                fields=['reverses'],
                name='refundreversal_one_per_refund',
            ),
            models.UniqueConstraint(
                fields=['organization', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='refundreversal_unique_idempotency_key_per_org',
            ),
        ]
