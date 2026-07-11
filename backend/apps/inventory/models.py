from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.core.models import OrganizationalModel, PublicIdMixin


class Product(PublicIdMixin, OrganizationalModel):
    CATEGORY_CHOICES = [
        ('medication', 'Medicamento'),
        ('food', 'Alimento'),
        ('accessory', 'Accesorio'),
        ('other', 'Otro'),
    ]

    # ADR p31 — unidades base compartidas por todas las presentaciones
    BASE_UNIT_CHOICES = [
        ('tablet', 'Tableta'),
        ('capsule', 'Cápsula'),
        ('ml', 'ml'),
        ('vial', 'Vial'),
        ('ampoule', 'Ampolleta'),
        ('piece', 'Pieza'),
        ('bag', 'Bolsa'),
        ('bottle', 'Frasco'),
        ('tube', 'Tubo'),
        ('kg', 'kg'),
        ('g', 'g'),
        ('unit', 'Unidad'),
    ]

    name = models.CharField(max_length=255)
    # Sin db_index: unique_together(organization, internal_code) ya crea el
    # índice compuesto que sirve toda query org-scoped. Un índice lone sobre
    # internal_code solo serviría búsquedas cross-org (no existen).
    internal_code = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    requires_prescription = models.BooleanField(default=False)
    # is_active, created_at, updated_at heredados de OrganizationalModel

    # Trazabilidad por lote (StockLot, spec 2026-07-10). manufacturer = fabricante
    # del PRODUCTO COMERCIAL (Zoetis/MSD), no el principio activo. tracks_lots es
    # opt-in: False = flujo idéntico al histórico (sin lotes, sin caducidad).
    manufacturer = models.CharField(max_length=255, blank=True, default='')
    tracks_lots = models.BooleanField(default=False)
    # Modo de cobro por defecto al consumir en consulta (A2). El auto-alta de
    # producto (p.ej. vacuna aplicada) lo usa; el usuario puede cambiarlo en Cargos.
    DEFAULT_COST_BEHAVIOR_CHOICES = [('charge', 'Cobrar'), ('included', 'Insumo')]
    default_cost_behavior = models.CharField(
        max_length=20, choices=DEFAULT_COST_BEHAVIOR_CHOICES, default='charge',
    )

    # ADR p31: stock real en unidades base (poblado por migration 0018)
    base_unit = models.CharField(
        max_length=20, choices=BASE_UNIT_CHOICES, blank=True, default='',
    )
    stock_quantity = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
    )
    min_stock = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        unique_together = [['organization', 'internal_code']]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=0),
                name='product_stock_quantity_non_negative',
            ),
        ]


class Presentation(PublicIdMixin, OrganizationalModel):
    UNIT_CHOICES = [
        ('tablet', 'Tableta'),
        ('capsule', 'Cápsula'),
        ('ml', 'ml'),
        ('vial', 'Vial'),
        ('ampoule', 'Ampolleta'),
        ('piece', 'Pieza'),
        ('bag', 'Bolsa'),
        ('bottle', 'Frasco'),
        ('tube', 'Tubo'),
        ('kg', 'kg'),
        ('g', 'g'),
        ('unit', 'Unidad'),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='presentations',
    )
    name = models.CharField(max_length=255)
    base_unit = models.CharField(max_length=20, choices=UNIT_CHOICES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ADR p31: formato comercial — conversion_factor = cuántas base_units por paquete
    # (semánticamente equivale a 'quantity'; se mantienen ambos durante transición)
    conversion_factor = models.DecimalField(
        max_digits=10, decimal_places=4, default=1,
    )
    barcode = models.CharField(max_length=100, blank=True, default='')
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )

    @property
    def is_low_stock(self):
        return self.product.stock_quantity <= self.product.min_stock

    def __str__(self):
        return f"{self.product.name} — {self.name}"

    class Meta:
        ordering = ['product__name', 'name']
        unique_together = [('product', 'name')]
        # Índices removidos (Capa 2): Index(['product']) era redundante con el
        # índice implícito de la FK product; Index(['stock']) era global (no
        # tenant-scoped) y de bajo valor (is_low_stock compara columna-vs-columna,
        # no usa el índice). Si stock__gt se vuelve hot, usar (organization, stock).
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock__gte=0),
                name="presentation_stock_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(sale_price__gt=0),
                name="presentation_sale_price_positive",
            ),
        ]


class StockLot(PublicIdMixin, OrganizationalModel):
    """
    Lote/batch físico de un Product con `tracks_lots=True` (spec inventario
    2026-07-10). El stock vive en DOS niveles: `Product.stock_quantity` = agregado
    autoritativo; `StockLot.quantity_on_hand` = saldo por lote (base-units).
    Invariante: Σ lotes == Product.stock_quantity (verificado por
    `audit_stock_integrity`). El escritor único sigue siendo `apply_stock_movement`.

    Estados ALMACENADOS (administrativos, no derivables): active | quarantined | recalled.
    Estados DERIVADOS (fuente de verdad = dato, sin cron, sin drift):
        expired (expiry_date < hoy) | consumed (quantity_on_hand <= 0).
    `effective_status` expone los 5 con precedencia BINDING (no reordenar):
        RECALLED → QUARANTINED → EXPIRED → CONSUMED → ACTIVE.
    """
    STATUS_ACTIVE = 'active'
    STATUS_QUARANTINED = 'quarantined'
    STATUS_RECALLED = 'recalled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Activo'),
        (STATUS_QUARANTINED, 'En cuarentena'),
        (STATUS_RECALLED, 'Retirado'),
    ]

    # effective_status (derivado, NO columna)
    EFFECTIVE_RECALLED = 'recalled'
    EFFECTIVE_QUARANTINED = 'quarantined'
    EFFECTIVE_EXPIRED = 'expired'
    EFFECTIVE_CONSUMED = 'consumed'
    EFFECTIVE_ACTIVE = 'active'

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='lots',
    )
    lot_number = models.CharField(max_length=100)
    expiry_date = models.DateField(null=True, blank=True)
    received_at = models.DateField(null=True, blank=True)
    quantity_on_hand = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
    )
    # Snapshot del proveedor. La FK `supplier` se agregará AL LADO cuando exista el
    # módulo Compras (spec §12) — sin renombrar, sin migración rara.
    supplier_name = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    @property
    def effective_status(self):
        # Precedencia BINDING: RECALLED → QUARANTINED → EXPIRED → CONSUMED → ACTIVE.
        if self.status == self.STATUS_RECALLED:
            return self.EFFECTIVE_RECALLED
        if self.status == self.STATUS_QUARANTINED:
            return self.EFFECTIVE_QUARANTINED
        if self.expiry_date and self.expiry_date < timezone.localdate():
            return self.EFFECTIVE_EXPIRED
        if self.quantity_on_hand <= 0:
            return self.EFFECTIVE_CONSUMED
        return self.EFFECTIVE_ACTIVE

    @property
    def is_consumable(self):
        """Elegible para consumo/FEFO: activo, no vencido y con saldo."""
        return self.effective_status == self.EFFECTIVE_ACTIVE

    def clean(self):
        # El lote hereda el tenant del producto — nunca cross-org.
        if (self.product_id and self.organization_id
                and self.product.organization_id != self.organization_id):
            raise ValidationError(
                "El lote debe pertenecer a la misma organización que el producto."
            )

    def __str__(self):
        return f"{self.product.name} — lote {self.lot_number}"

    class Meta:
        # Orden natural FEFO: caducidad ascendente (nulls al final por default de
        # Postgres en ASC). El id desempata de forma determinista.
        ordering = ['expiry_date', 'id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_on_hand__gte=0),
                name='stocklot_quantity_non_negative',
            ),
            models.UniqueConstraint(
                fields=['product', 'lot_number', 'expiry_date'],
                name='stocklot_product_lot_expiry_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'product', 'expiry_date'],
                         name='idx_stocklot_org_prod_exp'),
            models.Index(fields=['organization', 'status'],
                         name='idx_stocklot_org_status'),
        ]


class StockMovement(OrganizationalModel):
    MOVEMENT_TYPES = [
        ('in', 'Entrada'),
        ('out', 'Salida'),
        ('adjustment', 'Ajuste'),
    ]

    QUANTITY_UNIT_CHOICES = [
        ('presentation', 'Unidades de presentación (legacy)'),
        ('base', 'Unidades base (ADR p31)'),
    ]

    presentation = models.ForeignKey(
        Presentation,
        on_delete=models.CASCADE,
        related_name='movements',
    )
    # ADR p31: product FK para movimientos en base_units
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_movements',
        null=True,
        blank=True,
    )
    # Trazabilidad por lote (spec 2026-07-10). Nullable: movimientos legacy y de
    # productos sin `tracks_lots` lo dejan null. `lot_number` = snapshot
    # denormalizado para que el ledger conserve la identidad aunque el lote se borre.
    lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movements',
    )
    lot_number = models.CharField(max_length=100, blank=True, default='')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_unit = models.CharField(
        max_length=20,
        choices=QUANTITY_UNIT_CHOICES,
        default='presentation',
    )
    reason = models.CharField(max_length=255, blank=True)
    medical_record = models.ForeignKey(
        'medical_records.MedicalRecord',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements',
    )
    invoice = models.ForeignKey(
        'billing.Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements',
    )
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements_created',
    )
    # created_at heredado de OrganizationalModel

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Capa 3 — analytics. ProductDailyConsumption + "días de stock
            # restantes" calculan consumo medio sobre ventana móvil de
            # movements por presentation.
            models.Index(fields=['organization', 'presentation', '-created_at'],
                         name='idx_stockmov_org_pres_created'),
            # P1-2: CursorPagination ordena por (-created_at, -id) filtrando
            # por org. Cursor hace keyset scan → este índice lo sirve directo.
            models.Index(fields=['organization', '-created_at', '-id'],
                         name='idx_stockmov_org_created_id'),
        ]


class MedicalRecordProduct(OrganizationalModel):
    """
    Productos consumidos durante una consulta médica.
    El stock se ajusta automáticamente via save() y delete().

    cost_behavior='charge'   → descuenta stock + crea InvoiceItem (default)
    cost_behavior='included' → descuenta stock + NO crea InvoiceItem
                               (insumo incluido en costo del servicio)
    """
    COST_BEHAVIOR_CHOICES = [
        ('charge', 'Cobrar al cliente'),
        ('included', 'Incluido en costo de servicio'),
    ]

    medical_record = models.ForeignKey(
        'medical_records.MedicalRecord',
        on_delete=models.CASCADE,
        related_name='products_used',
    )
    presentation = models.ForeignKey(
        Presentation,
        on_delete=models.PROTECT,
        related_name='medical_record_usages',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    cost_behavior = models.CharField(
        max_length=20,
        choices=COST_BEHAVIOR_CHOICES,
        default='charge',
    )
    # Trazabilidad por lote (spec 2026-07-10, B2a). Nullable: productos sin
    # tracks_lots lo dejan null. Para productos con tracks_lots es el lote del que
    # se consumió — inmutable por línea (como cost_behavior). El consumo/reverso de
    # stock se hace SIEMPRE sobre este lote (consume_product / restock_product).
    lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='medical_record_usages',
    )

    class Meta:
        unique_together = [['medical_record', 'presentation']]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cost_behavior__in=['charge', 'included']),
                name='medicalrecordproduct_cost_behavior_valid',
            ),
        ]

    def save(self, *args, **kwargs):
        # Hereda organization del medical_record — sin query extra
        if self.medical_record_id and not self.organization_id:
            self.organization_id = self.medical_record.organization_id

        from django.db import connection, transaction
        from .services import consume_product, restock_product
        locked_presentation = kwargs.pop('locked_presentation', None)
        previous_quantity = kwargs.pop('previous_quantity', None)

        assert connection.in_atomic_block, (
            "MedicalRecordProduct.save() debe llamarse dentro de transaction.atomic(); "
            "sin tx el select_for_update() interno no aplica lock real y pierde la "
            "garantía de serialización contra movimientos de stock concurrentes."
        )
        if locked_presentation is None:
            import logging
            logging.getLogger(__name__).warning(
                "MedicalRecordProduct.save() invocado sin locked_presentation — "
                "fallback a lock interno. Llamada fuera de la view oficial. "
                "mr_id=%s pres_id=%s",
                self.medical_record_id, self.presentation_id,
            )

        with transaction.atomic():
            if self.pk:
                if previous_quantity is None:
                    old = MedicalRecordProduct.objects.select_for_update().get(pk=self.pk)
                    previous_quantity = old.quantity
                diff = self.quantity - previous_quantity
                if diff != 0:
                    fresh = locked_presentation or Presentation.objects.select_for_update().get(pk=self.presentation_id)
                    self.presentation = fresh
            else:
                fresh = locked_presentation or Presentation.objects.select_for_update().get(pk=self.presentation_id)
                self.presentation = fresh

            super().save(*args, **kwargs)

            cf = self.presentation.conversion_factor or 1
            # Consumo/reverso vía la única entrada (consume_product/restock_product),
            # siempre sobre self.lot (None en productos sin tracks_lots → path histórico).
            if self.pk and previous_quantity is not None:
                diff = self.quantity - previous_quantity
                if diff > 0:
                    consume_product(
                        presentation=self.presentation,
                        quantity_base=diff * cf,
                        organization=self.medical_record.organization,
                        lot=self.lot,
                        reason='Ajuste por edición de consulta médica',
                        medical_record=self.medical_record,
                    )
                elif diff < 0:
                    restock_product(
                        presentation=self.presentation,
                        quantity_base=abs(diff) * cf,
                        organization=self.medical_record.organization,
                        lot=self.lot,
                        reason='Ajuste por edición de consulta médica',
                        medical_record=self.medical_record,
                    )
            elif previous_quantity is None:
                consume_product(
                    presentation=self.presentation,
                    quantity_base=self.quantity * cf,
                    organization=self.medical_record.organization,
                    lot=self.lot,
                    reason='Consumido en consulta médica',
                    medical_record=self.medical_record,
                )

    def delete(self, *args, **kwargs):
        from django.db import connection, transaction
        from .services import restock_product
        locked_presentation = kwargs.pop('locked_presentation', None)
        assert connection.in_atomic_block, (
            "MedicalRecordProduct.delete() debe llamarse dentro de transaction.atomic(); "
            "sin tx el select_for_update() interno no aplica lock real."
        )
        with transaction.atomic():
            fresh = locked_presentation or Presentation.objects.select_for_update().get(pk=self.presentation_id)
            cf = fresh.conversion_factor or 1
            # Reverso al MISMO lote del que se consumió (política P4).
            restock_product(
                presentation=fresh,
                quantity_base=self.quantity * cf,
                organization=self.medical_record.organization,
                lot=self.lot,
                reason='Reversión por eliminación de producto en consulta',
                medical_record=self.medical_record,
            )
            super().delete(*args, **kwargs)
