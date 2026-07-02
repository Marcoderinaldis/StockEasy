from django.db import models
from django.conf import settings

from inventory.models import StockMovement


class WasteRecord(models.Model):
    """
    Waste tracking record (Feature 2 + 6, P1).

    Each waste record creates a corresponding WASTE StockMovement via the service layer.
    The stock_movement field links to the append-only ledger entry.
    """

    # Use the canonical REASON_CATEGORY_CHOICES from StockMovement
    WASTE_CATEGORY_CHOICES = StockMovement.REASON_CATEGORY_CHOICES

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
    stock_movement = models.OneToOneField(
        'inventory.StockMovement',
        on_delete=models.PROTECT,
        related_name='waste_record',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.product.name} waste {self.quantity_wasted} on {self.recorded_at.date()}"
