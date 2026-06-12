"""
Waste service layer for StockEasy.

All waste recording MUST go through these service functions.
Each waste record creates a corresponding WASTE StockMovement atomically.
"""

from django.db import transaction


def record_waste_via_movement(product, quantity, waste_category, user, notes=None):
    """
    Record a waste entry and create the corresponding stock movement.

    Both operations are performed atomically within a transaction:
    1. Creates a WasteRecord with the waste details
    2. Creates a WASTE StockMovement via inventory.services
    3. Updates Product.stock_quantity

    Args:
        product: Product instance for wasted stock
        quantity: Decimal quantity in product's unit
        waste_category: One of WasteRecord.WASTE_CATEGORY_CHOICES
        user: CustomUser who recorded this waste
        notes: Optional notes (do not include personal names)

    Returns:
        WasteRecord: The created waste record

    Raises:
        ValueError: If quantity is not positive
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")
