"""
Waste service layer for StockEasy.

All waste recording MUST go through these service functions.
Each waste record creates a corresponding WASTE StockMovement atomically.
"""

from decimal import Decimal

from django.db import transaction

from inventory.models import Product, StockMovement
from inventory.services import (
    convert_quantity_between_units,
    _quantize_quantity,
    _snapshot_unit_cost,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
    QUANTITY_PRECISION,
)
from .models import WasteRecord


def record_waste(product, quantity, unit, waste_category, user, notes=None):
    """
    Record a waste entry and create the corresponding stock movement.

    Both operations are performed atomically within a transaction:
    1. Validates inputs
    2. Converts quantity to product's unit
    3. Creates a WASTE StockMovement
    4. Decrements Product.stock_quantity
    5. Creates a WasteRecord linked to the StockMovement

    Args:
        product: Product instance for wasted stock
        quantity: Decimal quantity in the specified unit
        unit: Unit instance for the entered quantity
        waste_category: One of StockMovement.REASON_CATEGORY_CHOICES (required)
        user: CustomUser who recorded this waste
        notes: Optional notes (do not include personal names)

    Returns:
        WasteRecord: The created waste record

    Raises:
        StockValidationError: If quantity is not positive or waste_category is missing
        UnitTypeMismatchError: If unit type does not match product's unit type
        InsufficientStockError: If waste would make stock negative
    """
    # Validate quantity is positive
    quantity_decimal = _quantize_quantity(quantity)
    if quantity_decimal <= Decimal('0'):
        raise StockValidationError('Quantity must be positive.')

    # Validate waste_category is provided (required for waste)
    if not waste_category or not waste_category.strip():
        raise StockValidationError('Waste category is required.')

    # Validate unit type compatibility
    if unit.unit_type != product.unit.unit_type:
        raise UnitTypeMismatchError(
            f'Unit type mismatch: {unit.name} ({unit.unit_type}) '
            f'cannot be used with {product.name} ({product.unit.unit_type}).'
        )

    # Convert quantity to product's unit
    quantity_in_product_unit = convert_quantity_between_units(
        quantity_decimal, unit, product.unit
    )

    with transaction.atomic():
        # Lock the product row for update
        locked_product = Product.objects.select_for_update().get(pk=product.pk)

        # Compute new stock - waste is an outflow
        new_stock = _quantize_quantity(
            locked_product.stock_quantity - quantity_in_product_unit
        )

        # Block if stock would go negative
        if new_stock < Decimal('0'):
            raise InsufficientStockError(
                f'Insufficient stock. Available: {locked_product.stock_quantity} '
                f'{locked_product.unit.name}. Requested waste: {quantity_in_product_unit} '
                f'{locked_product.unit.name}.'
            )

        # Create the WASTE StockMovement (append-only ledger entry)
        stock_movement = StockMovement.objects.create(
            product=locked_product,
            quantity=quantity_in_product_unit,
            unit_cost_snapshot=_snapshot_unit_cost(locked_product),
            movement_type='WASTE',
            reason_category=waste_category,
            reason_notes=notes or None,
            recorded_by=user,
        )

        # Decrement product stock
        locked_product.stock_quantity = new_stock
        locked_product.save(update_fields=['stock_quantity', 'updated_at'])

        # Create the WasteRecord linked to the movement
        waste_record = WasteRecord.objects.create(
            product=locked_product,
            quantity_wasted=quantity_in_product_unit,
            waste_category=waste_category,
            notes=notes or None,
            recorded_by=user,
            stock_movement=stock_movement,
        )

    return waste_record
