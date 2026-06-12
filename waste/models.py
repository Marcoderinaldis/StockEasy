from django.db import models
from django.conf import settings


class WasteRecord(models.Model):
    """
    Waste tracking record (Feature 2 + 6, P1).

    Each waste record creates a corresponding WASTE StockMovement via the service layer.
    """

    WASTE_CATEGORY_CHOICES = [
        ('Product expired', 'Product Expired'),
        ('Delivery damaged', 'Delivery Damaged'),
        ('Counting error', 'Counting Error'),
        ('Spillage/accidental waste', 'Spillage/Accidental Waste'),
        ('Void—entered in error', 'Void—Entered in Error'),
        ('Other', 'Other'),
    ]

    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='waste_records',
    )
    quantity_wasted = models.DecimalField(max_digits=10, decimal_places=4)
    waste_category = models.CharField(max_length=100, choices=WASTE_CATEGORY_CHOICES)
    notes = models.CharField(max_length=200, blank=True, null=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='waste_records_recorded',
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.product.name} waste {self.quantity_wasted} on {self.recorded_at.date()}"
