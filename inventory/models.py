from django.db import models
from django.conf import settings


class Unit(models.Model):
    """Measurement unit with conversion to base units (g, ml, or count)."""

    UNIT_TYPE_CHOICES = [
        ('WEIGHT', 'Weight'),
        ('VOLUME', 'Volume'),
        ('COUNT', 'Count'),
    ]

    name = models.CharField(max_length=50, unique=True)
    unit_type = models.CharField(max_length=10, choices=UNIT_TYPE_CHOICES)
    conversion_to_base = models.DecimalField(max_digits=10, decimal_places=4)
    base_unit_name = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Category(models.Model):
    """Product category for grouping inventory items."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    """Central stock entity. Stock quantity MUST only be modified via service layer."""

    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name='products',
    )
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    reorder_level = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('name', 'category')]

    def __str__(self):
        return self.name

    @property
    def current_price(self):
        """
        Return the current active PurchasePrice for this product.

        An active price has effective_to=null. Returns the most recent one
        if multiple exist (ordered by -effective_from).

        Returns:
            PurchasePrice or None if no active price exists.
        """
        return self.prices.filter(effective_to__isnull=True).order_by('-effective_from').first()


class PurchasePrice(models.Model):
    """Historical pricing for products. effective_to=null means still active."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='prices',
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='GBP')
    effective_from = models.DateTimeField(auto_now_add=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='purchase_prices_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f"{self.product.name} — £{self.unit_price}"


class StockMovement(models.Model):
    """
    Append-only audit trail for all stock changes.

    NEVER update or delete StockMovement records directly.
    Use the service layer to create movements and handle voids.
    Double-void prevention is enforced in the service layer.
    """

    MOVEMENT_TYPE_CHOICES = [
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
        ('WASTE', 'Waste'),
        ('VOID', 'Void — Entered in Error'),
        ('ADJUSTMENT_IN', 'Adjustment In'),
        ('ADJUSTMENT_OUT', 'Adjustment Out'),
    ]

    REASON_CATEGORY_CHOICES = [
        ('Product expired', 'Product Expired'),
        ('Delivery damaged', 'Delivery Damaged'),
        ('Counting error', 'Counting Error'),
        ('Spillage/accidental waste', 'Spillage/Accidental Waste'),
        ('Void—entered in error', 'Void—Entered in Error'),
        ('Other', 'Other'),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='movements',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=4)
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES)
    reason_category = models.CharField(
        max_length=100,
        choices=REASON_CATEGORY_CHOICES,
        blank=True,
        null=True,
    )
    reason_notes = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Do not include personal names",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='stock_movements_recorded',
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    reference_id = models.CharField(max_length=50, blank=True, null=True)
    voids = models.OneToOneField(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='voided_by',
    )
    corrects = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='corrected_by',
    )

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.product.name} {self.movement_type} {self.quantity}"
