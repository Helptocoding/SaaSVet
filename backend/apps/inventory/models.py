from django.db import models
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
        from .services import apply_stock_movement
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
            if self.pk and previous_quantity is not None:
                diff = self.quantity - previous_quantity
                if diff != 0:
                    apply_stock_movement(
                        presentation=self.presentation,
                        quantity=abs(diff) * cf,
                        movement_type='out' if diff > 0 else 'in',
                        organization=self.medical_record.organization,
                        reason='Ajuste por edición de consulta médica',
                        medical_record=self.medical_record,
                    )
            elif previous_quantity is None:
                apply_stock_movement(
                    presentation=self.presentation,
                    quantity=self.quantity * cf,
                    movement_type='out',
                    organization=self.medical_record.organization,
                    reason='Consumido en consulta médica',
                    medical_record=self.medical_record,
                )

    def delete(self, *args, **kwargs):
        from django.db import connection, transaction
        from .services import apply_stock_movement
        locked_presentation = kwargs.pop('locked_presentation', None)
        assert connection.in_atomic_block, (
            "MedicalRecordProduct.delete() debe llamarse dentro de transaction.atomic(); "
            "sin tx el select_for_update() interno no aplica lock real."
        )
        with transaction.atomic():
            fresh = locked_presentation or Presentation.objects.select_for_update().get(pk=self.presentation_id)
            cf = fresh.conversion_factor or 1
            apply_stock_movement(
                presentation=fresh,
                quantity=self.quantity * cf,
                movement_type='in',
                organization=self.medical_record.organization,
                reason='Reversión por eliminación de producto en consulta',
                medical_record=self.medical_record,
            )
            super().delete(*args, **kwargs)
