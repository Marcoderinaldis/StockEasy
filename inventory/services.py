"""
Inventory service layer for StockEasy.

All stock mutations MUST go through these service functions.
Direct model updates to Product.stock_quantity are NEVER allowed.
StockMovement is append-only; no updates or deletes ever.
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from datetime import timedelta


def convert_quantity_between_units(quantity, from_unit, to_unit):
    """
    Convert a quantity from one unit to another.

    Both units must have the same unit_type.
    Converts via base unit (g, ml, or count).

    Args:
        quantity: Decimal or numeric quantity to convert
        from_unit: Unit instance to convert from
        to_unit: Unit instance to convert to

    Returns:
        Decimal: The converted quantity

    Raises:
        ValueError: If unit types do not match
    """
    if from_unit.unit_type != to_unit.unit_type:
        raise ValueError(
            f'Cannot convert between different unit types: '
            f'{from_unit.unit_type} and {to_unit.unit_type}'
        )

    if from_unit.id == to_unit.id:
        return Decimal(str(quantity))

    quantity_in_base = Decimal(str(quantity)) * from_unit.conversion_to_base
    converted_quantity = quantity_in_base / to_unit.conversion_to_base
    return converted_quantity


def record_stock_in(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record stock received (IN movement) and update product stock.

    Creates an append-only StockMovement record and updates Product.stock_quantity
    atomically within a transaction.

    Args:
        product: Product instance to add stock to
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this movement
        reference_id: Optional reference (e.g., invoice ID)

    Returns:
        StockMovement: The created movement record

    Raises:
        ValueError: If quantity is not positive
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def record_stock_out(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record stock removed (OUT movement) and update product stock.

    Creates an append-only StockMovement record and updates Product.stock_quantity
    atomically within a transaction.

    Args:
        product: Product instance to remove stock from
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this movement
        reference_id: Optional reference (e.g., adjustment ticket)

    Returns:
        StockMovement: The created movement record

    Raises:
        ValueError: If quantity is not positive
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def record_waste(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record waste and update product stock.

    Creates an append-only WASTE StockMovement record and updates Product.stock_quantity
    atomically within a transaction.

    Args:
        product: Product instance for wasted stock
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this movement
        reference_id: Optional reference

    Returns:
        StockMovement: The created movement record

    Raises:
        ValueError: If quantity is not positive
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def void_movement(movement, reason_notes, user):
    """
    Void an existing stock movement by creating a VOID movement.

    StockMovement is append-only, so this creates a new VOID movement
    that reverses the effect of the original movement.

    Double-void prevention: If a VOID movement exists for the same product
    within the last 5 minutes, this function will reject the request.

    Args:
        movement: StockMovement instance to void
        reason_notes: Reason for voiding (required)
        user: CustomUser who is voiding the movement

    Returns:
        StockMovement: The created VOID movement record

    Raises:
        ValueError: If movement is already a VOID type
        ValueError: If double-void detected (VOID exists for same product in last 5 mins)
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def record_adjustment_in(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record positive stock adjustment (ADJUSTMENT_IN) and update product stock.

    Args:
        product: Product instance to adjust
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this adjustment
        reference_id: Optional reference (e.g., adjustment ticket)

    Returns:
        StockMovement: The created movement record
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def record_adjustment_out(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record negative stock adjustment (ADJUSTMENT_OUT) and update product stock.

    Args:
        product: Product instance to adjust
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this adjustment
        reference_id: Optional reference (e.g., adjustment ticket)

    Returns:
        StockMovement: The created movement record
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")
