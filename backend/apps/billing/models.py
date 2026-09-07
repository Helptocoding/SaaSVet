import logging
import uuid
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
        ('posted', 'Emitida'),
        ('paid', 'Pagada'),
        ('voided', 'Anulada'),
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
    medical_record = models.ForeignKey(
        'medical_records.MedicalRecord',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
    )
    appointment = models.ForeignKey(
        'appointments.Appointment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
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

    checkout = models.OneToOneField(
        'billing.Checkout', on_delete=models.PROTECT, null=True, blank=True,
        related_name='invoice',
    )
    supersedes_invoice = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='superseded_by',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='posted')
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
    due_at = models.DateTimeField(null=True, blank=True, editable=False)
    credit_reason = models.CharField(max_length=80, blank=True, editable=False)

    notes = models.TextField(blank=True)

    # ------------------------------------------------------------------
    # Analytics anchors (editable=False; solo escritos por billing/services.py).
    # Cualquier mutación fuera de los services rompe el contrato analítico
    # (ver docs/dashboard-metrics-contract.md §2.7).
    # ------------------------------------------------------------------
    paid_at = models.DateTimeField(null=True, blank=True, editable=False)
    posted_at = models.DateTimeField(null=True, blank=True, editable=False)
    voided_at = models.DateTimeField(null=True, blank=True, editable=False)

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
    posted_at_source = models.CharField(
        max_length=24, choices=ANCHOR_SOURCE_CHOICES,
        default='service', editable=False,
    )
    voided_at_source = models.CharField(
        max_length=24, choices=ANCHOR_SOURCE_CHOICES,
        default='service', editable=False,
    )
    # created_at, updated_at heredados de OrganizationalModel

    def clean(self):
        org = self.organization_id
        if self._state.adding and not self.checkout_id:
            raise ValidationError('Toda factura nueva debe emitirse desde un Checkout.')
        if org and self.owner_id and self.owner.organization_id != org:
            raise ValidationError("El propietario no pertenece a la misma organizacion que la factura.")
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organizacion que la factura.")
        if org and self.appointment_id and self.appointment.organization_id != org:
            raise ValidationError("La cita no pertenece a la misma organizacion que la factura.")
        if org and self.medical_record_id and self.medical_record.organization_id != org:
            raise ValidationError("El registro medico no pertenece a la misma organizacion que la factura.")

    def save(self, *args, **kwargs):
        # Invoice ya no es un carrito editable: toda fila representa un
        # documento financiero emitido y debe nacer con su anchor de emisión.
        if self.posted_at is None:
            self.posted_at = timezone.now()
        super().save(*args, **kwargs)

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
        # stale durante la construcción transaccional del documento posted.
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
            models.Index(fields=["organization", "status", "posted_at"],
                         name="idx_inv_org_status_post"),
            models.Index(fields=["organization", "status", "voided_at"],
                         name="idx_inv_org_status_void"),
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
                condition=~models.Q(status='voided') | models.Q(voided_at__isnull=False),
                name="invoice_voided_status_requires_voided_at",
            ),
            models.CheckConstraint(
                condition=models.Q(posted_at__isnull=False),
                name="invoice_posted_at_required",
            ),
        ]


class MedicalRecordBillingContext(OrganizationalModel):
    """Tax snapshot captured when the first billable clinical charge appears."""
    medical_record = models.OneToOneField(
        'medical_records.MedicalRecord', on_delete=models.PROTECT,
        related_name='billing_context',
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4)
    tax_effective_at = models.DateTimeField()
    provenance = models.CharField(max_length=40, default='first_billable')

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tax_rate__gte=0) & models.Q(tax_rate__lte=1),
                name='billing_mr_context_tax_rate_range',
            ),
        ]


class ClinicalChargeEntry(OrganizationalModel):
    """Immutable priced cycle for one billable clinical source."""
    LIFECYCLE_CHOICES = (('active', 'Activo'), ('closed', 'Cerrado'))
    medical_record = models.ForeignKey(
        'medical_records.MedicalRecord', on_delete=models.PROTECT,
        related_name='clinical_charge_entries',
    )
    medical_record_service = models.ForeignKey(
        'medical_records.MedicalRecordService', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='charge_entries',
    )
    medical_record_product = models.ForeignKey(
        'inventory.MedicalRecordProduct', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='charge_entries',
    )
    source_kind = models.CharField(
        max_length=24, choices=(('service', 'Servicio'), ('product', 'Producto')),
    )
    source_pk = models.PositiveBigIntegerField()
    cycle_number = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='MXN')
    price_effective_at = models.DateTimeField()
    lifecycle = models.CharField(max_length=12, choices=LIFECYCLE_CHOICES, default='active')
    current_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=40, blank=True)
    supersedes_entry = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='superseded_by',
    )

    def clean(self):
        if self._state.adding and bool(self.medical_record_service_id) == bool(self.medical_record_product_id):
            raise ValidationError('Un ciclo clínico nuevo requiere exactamente una fuente.')
        if self.medical_record_id and self.medical_record.organization_id != self.organization_id:
            raise ValidationError('La consulta y el ciclo deben pertenecer a la misma organización.')

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(medical_record_service__isnull=False, medical_record_product__isnull=True)
                    | models.Q(medical_record_service__isnull=True, medical_record_product__isnull=False)
                    | models.Q(medical_record_service__isnull=True, medical_record_product__isnull=True)
                ),
                name='billing_charge_entry_at_most_one_source',
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name='billing_charge_entry_price_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(current_quantity__gte=0),
                name='billing_charge_entry_qty_nonnegative',
            ),
            models.UniqueConstraint(
                fields=('medical_record_service', 'cycle_number'),
                condition=models.Q(medical_record_service__isnull=False),
                name='billing_charge_service_cycle_unique',
            ),
            models.UniqueConstraint(
                fields=('medical_record_product', 'cycle_number'),
                condition=models.Q(medical_record_product__isnull=False),
                name='billing_charge_product_cycle_unique',
            ),
            models.UniqueConstraint(
                fields=('medical_record_service',),
                condition=models.Q(medical_record_service__isnull=False, lifecycle='active'),
                name='billing_charge_one_active_service_cycle',
            ),
            models.UniqueConstraint(
                fields=('medical_record_product',),
                condition=models.Q(medical_record_product__isnull=False, lifecycle='active'),
                name='billing_charge_one_active_product_cycle',
            ),
        ]


class ClinicalChargeQuantityEvent(OrganizationalModel):
    """Append-only quantity mutation inside a priced clinical cycle."""
    entry = models.ForeignKey(
        ClinicalChargeEntry, on_delete=models.PROTECT, related_name='quantity_events',
    )
    delta = models.DecimalField(max_digits=10, decimal_places=2)
    resulting_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    mutation_key = models.CharField(max_length=100)
    reason = models.CharField(max_length=80)
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='clinical_charge_quantity_events',
    )
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('entry', 'mutation_key'),
                name='billing_charge_quantity_mutation_unique',
            ),
        ]


class ClinicalChargeSnapshot(OrganizationalModel):
    """Immutable close-time projection copied into Checkout."""
    entry = models.OneToOneField(
        ClinicalChargeEntry, on_delete=models.PROTECT, related_name='snapshot',
    )
    billing_context = models.ForeignKey(
        MedicalRecordBillingContext, on_delete=models.PROTECT,
        related_name='charge_snapshots',
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='MXN')
    snapshotted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='billing_charge_snapshot_qty_positive',
            ),
        ]


class Checkout(PublicIdMixin, OrganizationalModel):
    ORIGIN_CHOICES = (('consultation', 'Consulta'), ('direct_sale', 'Venta directa'))
    KIND_CHOICES = (('primary_consultation', 'Consulta primaria'), ('prescription_supplement', 'Suplemento'), ('direct_sale', 'Venta directa'), ('replacement', 'Reemplazo'))
    LIFECYCLE_CHOICES = (('open', 'Abierto'), ('completed', 'Completado'), ('abandoned', 'Abandonado'))
    COMPLETION_CHOICES = (('no_charge', 'Sin cargo'), ('posted_paid', 'Cobrado'), ('posted_unpaid', 'Pendiente'), ('replacement_waived', 'Condonado'))
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES)
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    medical_record = models.ForeignKey('medical_records.MedicalRecord', on_delete=models.PROTECT, null=True, blank=True, related_name='checkouts')
    replaces_invoice = models.OneToOneField('billing.Invoice', on_delete=models.PROTECT, null=True, blank=True, related_name='replacement_checkout')
    owner = models.ForeignKey('users.User', on_delete=models.PROTECT, related_name='owned_checkouts', null=True, blank=True)
    customer = models.ForeignKey('patients.Owner', on_delete=models.PROTECT, related_name='checkouts')
    pet = models.ForeignKey('patients.Pet', on_delete=models.PROTECT, related_name='checkouts', null=True, blank=True)
    lifecycle = models.CharField(max_length=20, choices=LIFECYCLE_CHOICES, default='open')
    completion_kind = models.CharField(max_length=30, choices=COMPLETION_CHOICES, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    correction_due_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    abandoned_at = models.DateTimeField(null=True, blank=True)
    abandoned_reason = models.CharField(max_length=100, blank=True)
    operational_hold = models.CharField(max_length=30, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    def recalculate_totals(self):
        raw_subtotal = (
            CheckoutItem.all_objects.filter(checkout=self, is_active=True)
            .aggregate(s=Sum('subtotal'))['s']
        ) or Decimal('0.00')
        subtotal, tax_amount, total = invoice_totals(raw_subtotal, self.tax_rate)
        Checkout.all_objects.filter(pk=self.pk).update(
            subtotal=subtotal, tax_amount=tax_amount, total=total,
            version=models.F('version') + 1, updated_at=timezone.now(),
        )

    def clean(self):
        if self.customer_id and self.customer.organization_id != self.organization_id:
            raise ValidationError('El cliente no pertenece a la organización del Checkout.')
        if self.pet_id and self.pet.organization_id != self.organization_id:
            raise ValidationError('La mascota no pertenece a la organización del Checkout.')
        if self.pet_id and self.pet.owner_id != self.customer_id:
            raise ValidationError('La mascota no pertenece al cliente del Checkout.')
        if self.kind == 'replacement' and self.expires_at is not None:
            raise ValidationError('Un replacement no puede expirar.')
        if self.lifecycle == 'open' and self.completion_kind:
            raise ValidationError('Un Checkout abierto no puede tener resultado terminal.')
        if self.lifecycle == 'completed' and not self.completion_kind:
            raise ValidationError('Un Checkout completado requiere resultado terminal.')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('organization', 'medical_record', 'kind'), condition=models.Q(kind='primary_consultation', is_active=True), name='billing_checkout_one_primary_per_record'),
            models.CheckConstraint(condition=(~models.Q(kind='replacement') | models.Q(replaces_invoice__isnull=False)), name='billing_replacement_has_source_invoice'),
        ]


class CheckoutItem(OrganizationalModel):
    checkout = models.ForeignKey(Checkout, on_delete=models.PROTECT, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    source_kind = models.CharField(max_length=40)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, null=True, blank=True, related_name='checkout_items')
    presentation = models.ForeignKey('inventory.Presentation', on_delete=models.PROTECT, null=True, blank=True, related_name='checkout_items')
    # Immutable base-units-per-presentation captured when the commercial line is
    # created.  Catalog edits must never reinterpret an open or posted document.
    conversion_factor_snapshot = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
    )
    lot = models.ForeignKey('inventory.StockLot', on_delete=models.PROTECT, null=True, blank=True, related_name='checkout_items')
    prescription_item = models.ForeignKey('prescriptions.PrescriptionItem', on_delete=models.PROTECT, null=True, blank=True, related_name='checkout_items')
    medical_record_service = models.ForeignKey('medical_records.MedicalRecordService', on_delete=models.PROTECT, null=True, blank=True, related_name='checkout_items')
    medical_record_product = models.ForeignKey('inventory.MedicalRecordProduct', on_delete=models.PROTECT, null=True, blank=True, related_name='checkout_items')
    clinical_charge_snapshot = models.OneToOneField(
        ClinicalChargeSnapshot, on_delete=models.PROTECT, null=True, blank=True,
        related_name='checkout_item',
    )
    source_invoice_item = models.ForeignKey('billing.InvoiceItem', on_delete=models.PROTECT, null=True, blank=True, related_name='replacement_baseline_items')
    baseline_kind = models.CharField(max_length=30, blank=True)
    required_replacement_baseline = models.BooleanField(default=False)
    fulfillment_source = models.CharField(max_length=20, default='new')
    discount_type = models.CharField(max_length=10, choices=(('percentage', 'Porcentaje'), ('fixed', 'Monto fijo')), null=True, blank=True)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rx_attested = models.BooleanField(default=False)
    prescriber_name = models.CharField(max_length=255, blank=True)
    prescription_folio = models.CharField(max_length=100, blank=True)
    regulatory_revision = models.PositiveIntegerField(default=1)

    def save(self, *args, **kwargs):
        if self.checkout_id and not self.organization_id:
            self.organization_id = self.checkout.organization_id
        if self.presentation_id:
            if self.conversion_factor_snapshot is None:
                from apps.inventory.units import presentation_conversion_factor
                self.conversion_factor_snapshot = presentation_conversion_factor(self.presentation)
        elif self.conversion_factor_snapshot is not None:
            raise ValidationError(
                'Una línea sin presentación no puede tener factor de conversión.'
            )
        gross = money(self.quantity * self.unit_price)
        disc = discount_amount(gross, self.discount_type, self.discount_value)
        self.subtotal = line_subtotal(self.quantity, self.unit_price, disc)
        super().save(*args, **kwargs)
        self.checkout.recalculate_totals()

    def clean(self):
        if self.checkout_id and self.organization_id != self.checkout.organization_id:
            raise ValidationError('La línea y el Checkout deben pertenecer a la misma organización.')
        for source in (
            self.service, self.presentation, self.prescription_item,
            self.medical_record_service, self.medical_record_product,
            self.clinical_charge_snapshot,
        ):
            if source is not None and source.organization_id != self.organization_id:
                raise ValidationError('La fuente de la línea pertenece a otra organización.')

    def delete(self, *args, **kwargs):
        if self.required_replacement_baseline:
            raise ValidationError('No se puede eliminar una línea baseline de replacement.')
        checkout = self.checkout
        # La línea se retira de la preparación comercial, pero no se destruye:
        # puede ser la raíz de evidencia regulatoria append-only (receta externa).
        self.is_active = False
        super().save(update_fields=['is_active', 'updated_at'])
        checkout.recalculate_totals()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='billing_checkout_item_qty_positive'),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name='billing_checkout_item_price_nonnegative'),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0), name='billing_checkout_item_subtotal_nonnegative'),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        presentation__isnull=True,
                        conversion_factor_snapshot__isnull=True,
                    )
                    | models.Q(
                        presentation__isnull=False,
                        conversion_factor_snapshot__gt=0,
                        conversion_factor_snapshot__lte=Decimal('999999.9999'),
                    )
                ),
                name='billing_checkout_item_factor_snapshot_valid',
            ),
        ]


class CheckoutPrescriptionSelection(OrganizationalModel):
    DECISION_CHOICES = (
        ('pending', 'Pendiente'), ('accepted', 'Aceptada'), ('declined', 'Rechazada'),
    )
    checkout = models.ForeignKey(
        Checkout, on_delete=models.PROTECT, related_name='prescription_selections',
    )
    prescription_item = models.ForeignKey(
        'prescriptions.PrescriptionItem', on_delete=models.PROTECT,
        related_name='checkout_selections',
    )
    decision = models.CharField(max_length=12, choices=DECISION_CHOICES, default='pending')
    eligible_remaining_at_open = models.DecimalField(max_digits=14, decimal_places=4)
    decline_reason = models.CharField(max_length=30, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='checkout_prescription_decisions',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('checkout', 'prescription_item'),
                name='billing_checkout_rx_selection_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(eligible_remaining_at_open__gte=0),
                name='billing_checkout_rx_remaining_nonnegative',
            ),
        ]


class ObligationEvidence(OrganizationalModel):
    BASIS_CHOICES = (
        ('payment_authorization', 'Autorización de pago'),
        ('customer_acknowledgement', 'Aceptación del cliente'),
        ('preauthorized_terms', 'Términos preautorizados'),
    )
    checkout = models.OneToOneField(
        Checkout, on_delete=models.PROTECT, related_name='obligation_evidence',
    )
    invoice = models.OneToOneField(
        Invoice, on_delete=models.PROTECT, related_name='obligation_evidence',
    )
    basis = models.CharField(max_length=32, choices=BASIS_CHOICES)
    checkout_version = models.PositiveIntegerField()
    accepted_total = models.DecimalField(max_digits=10, decimal_places=2)
    accepting_party = models.CharField(max_length=255)
    captured_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='captured_obligation_evidence',
    )
    channel = models.CharField(max_length=20)
    reference = models.CharField(max_length=255, blank=True)
    accepted_at = models.DateTimeField()
    credit_authorized_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, null=True, blank=True,
        related_name='authorized_credit_obligations',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(accepted_total__gt=0),
                name='billing_obligation_evidence_total_positive',
            ),
        ]


class CollectionCase(PublicIdMixin, OrganizationalModel):
    invoice = models.OneToOneField(
        Invoice, on_delete=models.PROTECT, related_name='collection_case',
    )
    status = models.CharField(
        max_length=16,
        choices=(('open', 'Abierto'), ('resolved', 'Resuelto')),
        default='open',
    )
    resolution = models.CharField(max_length=24, blank=True)
    owner = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='owned_collection_cases',
    )
    review_due_at = models.DateTimeField()
    opened_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['organization', 'created_at'])]


class CheckoutDispute(PublicIdMixin, OrganizationalModel):
    """Persistent pre-post dispute; it never creates revenue by itself."""
    STATUS_CHOICES = (('open', 'Abierta'), ('resolved', 'Resuelta'))
    RESOLUTION_CHOICES = (
        ('accepted', 'Aceptado'),
        ('adjusted_or_waived', 'Ajustado o condonado'),
        ('enforced_under_terms', 'Exigible por términos'),
    )
    checkout = models.ForeignKey(
        Checkout, on_delete=models.PROTECT, related_name='disputes',
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, null=True, blank=True,
        related_name='source_checkout_disputes',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='open')
    disputed_item_ids = models.JSONField(default=list)
    disputed_amount = models.DecimalField(max_digits=10, decimal_places=2)
    statement = models.TextField()
    evidence = models.JSONField(default=dict, blank=True)
    owner = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='owned_checkout_disputes',
    )
    opened_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='opened_checkout_disputes',
    )
    opened_at = models.DateTimeField()
    review_due_at = models.DateTimeField()
    resolution = models.CharField(max_length=32, choices=RESOLUTION_CHOICES, blank=True)
    resolution_reason = models.TextField(blank=True)
    resolution_evidence = models.JSONField(default=dict, blank=True)
    resolved_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, null=True, blank=True,
        related_name='resolved_checkout_disputes',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('checkout',), condition=models.Q(status='open'),
                name='billing_checkout_one_open_dispute',
            ),
            models.CheckConstraint(
                condition=models.Q(disputed_amount__gt=0),
                name='billing_checkout_dispute_amount_positive',
            ),
        ]


class CheckoutEvent(OrganizationalModel):
    checkout = models.ForeignKey(Checkout, on_delete=models.PROTECT, related_name='events')
    kind = models.CharField(max_length=40)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason_code = models.CharField(max_length=50)
    evidence = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='billing_checkout_events',
    )
    occurred_at = models.DateTimeField()


class CheckoutEstimate(PublicIdMixin, OrganizationalModel):
    checkout = models.ForeignKey(Checkout, on_delete=models.PROTECT, related_name='estimates')
    checkout_version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    content_hash = models.CharField(max_length=64)
    generated_at = models.DateTimeField()
    generated_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='generated_checkout_estimates',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('checkout', 'checkout_version'),
                name='billing_checkout_estimate_version_unique',
            ),
        ]


class StockAllocation(OrganizationalModel):
    invoice_item = models.ForeignKey(
        'billing.InvoiceItem', on_delete=models.PROTECT, related_name='stock_allocations',
    )
    checkout_item = models.ForeignKey(
        CheckoutItem, on_delete=models.PROTECT, related_name='stock_allocations',
    )
    presentation = models.ForeignKey(
        'inventory.Presentation', on_delete=models.PROTECT, related_name='billing_allocations',
    )
    lot = models.ForeignKey(
        'inventory.StockLot', on_delete=models.PROTECT, null=True, blank=True,
        related_name='billing_allocations',
    )
    quantity_base = models.DecimalField(max_digits=14, decimal_places=4)
    allocated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_base__gt=0),
                name='billing_stock_allocation_qty_positive',
            ),
        ]


class StockDispositionEvent(OrganizationalModel):
    """Custodia física y efecto de inventario, separados del evento financiero."""
    allocation = models.ForeignKey(
        StockAllocation, on_delete=models.PROTECT, related_name='disposition_events',
    )
    credit_note_item = models.ForeignKey(
        'billing.CreditNoteItem', on_delete=models.PROTECT, null=True, blank=True,
        related_name='stock_disposition_events',
    )
    kind = models.CharField(
        max_length=24,
        choices=(
            ('delivered', 'Entregado'),
            ('returned_restocked', 'Devuelto y reingresado'),
            ('returned_discarded', 'Devuelto y descartado'),
            ('retained_after_refund', 'Retenido después de reembolso'),
        ),
    )
    quantity_base = models.DecimalField(max_digits=14, decimal_places=4)
    stock_delta = models.DecimalField(max_digits=14, decimal_places=4)
    custody = models.CharField(
        max_length=16,
        choices=(('customer', 'Cliente'), ('clinic', 'Clínica'), ('discarded', 'Descartado')),
    )
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_base__gt=0),
                name='billing_stock_disposition_qty_positive',
            ),
            models.UniqueConstraint(
                fields=('allocation', 'kind'),
                condition=models.Q(kind='delivered'),
                name='billing_stock_allocation_delivered_once',
            ),
            models.UniqueConstraint(
                fields=('credit_note_item', 'allocation'),
                condition=models.Q(credit_note_item__isnull=False),
                name='billing_stock_disposition_credit_allocation_unique',
            ),
        ]


class PrescriptionFulfillmentEvent(OrganizationalModel):
    prescription_item = models.ForeignKey(
        'prescriptions.PrescriptionItem', on_delete=models.PROTECT,
        related_name='fulfillment_events',
    )
    invoice_item = models.ForeignKey(
        'billing.InvoiceItem', on_delete=models.PROTECT,
        related_name='prescription_fulfillment_events',
    )
    allocation = models.ForeignKey(
        StockAllocation, on_delete=models.PROTECT, related_name='fulfillment_events',
    )
    credit_note_item = models.ForeignKey(
        'billing.CreditNoteItem', on_delete=models.PROTECT, null=True, blank=True,
        related_name='prescription_fulfillment_events',
    )
    stock_disposition_event = models.OneToOneField(
        StockDispositionEvent, on_delete=models.PROTECT, null=True, blank=True,
        related_name='prescription_fulfillment_event',
    )
    kind = models.CharField(
        max_length=20,
        choices=(
            ('dispensed', 'Dispensado'),
            ('returned', 'Devuelto físicamente'),
            ('redelivered', 'Reentregado tras devolución'),
        ),
        default='dispensed',
    )
    # quantity_delta es exclusivamente la contribución al límite legal Rx.
    # Una devolución no la hace negativa; una reentrega demostrada aporta cero.
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=4)
    physical_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_delta__gte=0),
                name='billing_rx_cap_delta_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(physical_quantity__gt=0),
                name='billing_rx_physical_quantity_positive',
            ),
            models.UniqueConstraint(
                fields=('invoice_item', 'kind'),
                condition=models.Q(kind='dispensed'),
                name='billing_rx_initial_fulfillment_once',
            ),
            models.UniqueConstraint(
                fields=('credit_note_item', 'allocation'),
                condition=models.Q(credit_note_item__isnull=False),
                name='billing_rx_return_credit_allocation_unique',
            ),
        ]


class ReplacementWaiver(OrganizationalModel):
    checkout = models.OneToOneField(Checkout, on_delete=models.PROTECT, related_name='replacement_waiver')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason_code = models.CharField(max_length=50)
    evidence = models.JSONField(default=dict)
    baseline_hash = models.CharField(max_length=128)
    waived_by = models.ForeignKey('users.User', on_delete=models.PROTECT, related_name='replacement_waivers')
    occurred_at = models.DateTimeField()

    def clean(self):
        if self.checkout_id:
            if self.checkout.kind != 'replacement':
                raise ValidationError('El waiver solo aplica a un Checkout replacement.')
            if self.organization_id != self.checkout.organization_id:
                raise ValidationError('El waiver y el Checkout deben pertenecer a la misma organización.')


class CommandReceipt(OrganizationalModel):
    """Claim idempotente de un comando de dominio y su respuesta estable."""
    receipt_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    command_kind = models.CharField(max_length=50)
    idempotency_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    aggregate_type = models.CharField(max_length=40)
    aggregate_public_id = models.CharField(max_length=100)
    canonical_schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    status = models.CharField(
        max_length=16,
        choices=(('processing', 'Procesando'), ('succeeded', 'Completado'), ('failed', 'Fallido')),
        default='processing',
    )
    response_data = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='billing_command_receipts',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('organization', 'command_kind', 'idempotency_key'),
                name='billing_command_receipt_identity',
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

    # Provenance inmutable copiada desde Checkout al postear una selección Rx.
    # Doble función:
    #   1) Provenance: qué línea de receta (PrescriptionItem) surtió esta línea.
    #   2) Discriminador del descuento de stock: en una factura `consultation`,
    #      los ítems sincronizados desde MedicalRecordProduct YA descontaron stock
    #      al consumirse en consulta; estos ítems dispensados NO. La única ruta de
    #      settlement del post usa este FK para saber qué ítems de una consulta
    #      liquidan stock. En `direct_sale` todos los ítems liquidan. La
    #      Prescription interna es el respaldo legal
    #      del producto requires_prescription (no se exige atestación externa,
    #      ADR p26); el permiso billing.rx_dispense se valida en la view.
    dispensed_from_prescription_item = models.ForeignKey(
        'prescriptions.PrescriptionItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dispensed_invoice_items',
    )
    # Trazabilidad por lote (spec 2026-07-10, B2b). Nullable: productos sin
    # tracks_lots lo dejan null. Para ítems que LIQUIDAN stock (venta directa /
    # dispensación) de un producto tracks_lots, es el lote del que se descuenta al
    # postear y al que se revierte mediante disposición/retorno (P4). Inmutable.
    lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_items',
    )
    # Immutable unit contract copied from CheckoutItem at posting time.
    conversion_factor_snapshot = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
    )
    external_rx_attestation = models.ForeignKey(
        'billing.ExternalPrescriptionAttestation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='invoice_items',
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
        if self.pk is not None:
            raise ValidationError('Las líneas de una factura emitida son inmutables.')
        # Hereda organization del invoice — sin query extra
        if self.invoice_id and not self.organization_id:
            self.organization_id = self.invoice.organization_id
        if self.presentation_id:
            if self.conversion_factor_snapshot is None:
                from apps.inventory.units import presentation_conversion_factor
                self.conversion_factor_snapshot = presentation_conversion_factor(self.presentation)
        elif self.conversion_factor_snapshot is not None:
            raise ValidationError(
                'Una línea sin presentación no puede tener factor de conversión.'
            )

        self._warn_if_not_atomic('save')

        gross = money(self.quantity * self.unit_price)
        disc = discount_amount(gross, self.discount_type, self.discount_value)
        self.subtotal = line_subtotal(self.quantity, self.unit_price, disc)

        super().save(*args, **kwargs)
        self.invoice.recalculate_totals()

    def delete(self, *args, **kwargs):
        raise ValidationError('Las líneas de una factura emitida no se eliminan; use una nota de crédito.')

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
            models.CheckConstraint(
                condition=(
                    Q(
                        presentation__isnull=True,
                        conversion_factor_snapshot__isnull=True,
                    )
                    | Q(
                        presentation__isnull=False,
                        conversion_factor_snapshot__gt=0,
                        conversion_factor_snapshot__lte=Decimal('999999.9999'),
                    )
                ),
                name='billing_invoice_item_factor_snapshot_valid',
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
    command_receipt = models.ForeignKey(
        CommandReceipt, on_delete=models.PROTECT, null=True, blank=True,
        related_name='payment_events',
    )
    command_line_index = models.PositiveSmallIntegerField(null=True, blank=True)
    financial_identity_version = models.PositiveSmallIntegerField(default=1, editable=False)
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
            models.UniqueConstraint(
                fields=['command_receipt', 'command_line_index'],
                condition=models.Q(command_receipt__isnull=False),
                name='payment_unique_child_per_command_receipt',
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
        null=True, blank=True,
    )
    checkout_item = models.ForeignKey(
        CheckoutItem, on_delete=models.PROTECT, related_name='rx_attestations',
        null=True, blank=True,
    )
    regulatory_revision = models.PositiveIntegerField(default=1)
    line_fingerprint = models.CharField(max_length=64, blank=True)
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
    supersedes_attestation = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='superseded_by',
    )
    correction_reason = models.CharField(max_length=100, blank=True)
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
            models.CheckConstraint(
                condition=models.Q(invoice__isnull=False) | models.Q(checkout_item__isnull=False),
                name='rxattestation_has_document_or_checkout_item',
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
        ('retained', 'El cliente conserva el producto'),
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
    command_receipt = models.ForeignKey(
        CommandReceipt, on_delete=models.PROTECT, null=True, blank=True,
        related_name='refund_payment_events',
    )
    command_line_index = models.PositiveSmallIntegerField(null=True, blank=True)
    financial_identity_version = models.PositiveSmallIntegerField(default=1, editable=False)
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
            models.UniqueConstraint(
                fields=['command_receipt', 'command_line_index'],
                condition=models.Q(command_receipt__isnull=False),
                name='refundpayment_unique_child_per_command_receipt',
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
    command_receipt = models.ForeignKey(
        CommandReceipt, on_delete=models.PROTECT, null=True, blank=True,
        related_name='refund_reversal_events',
    )
    command_line_index = models.PositiveSmallIntegerField(null=True, blank=True)
    financial_identity_version = models.PositiveSmallIntegerField(default=1, editable=False)
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
            models.UniqueConstraint(
                fields=['command_receipt', 'command_line_index'],
                condition=models.Q(command_receipt__isnull=False),
                name='refundreversal_unique_child_per_command_receipt',
            ),
        ]
