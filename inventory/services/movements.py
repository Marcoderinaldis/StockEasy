"""
Stock movement recording functions.
"""

from decimal import Decimal

from django.db import transaction

from ..models import Product, StockMovement
from .exceptions import (
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
)
from .helpers import (
    _quantize_quantity,
    convert_quantity_between_units,
    _snapshot_unit_cost,
)


def record_movement(
    product,
    movement_type,
    quantity,
    unit,
    reason_category=None,
    reason_notes=None,
    user=None,
    reference_id=None,
):
    """
    Record a stock movement and update product stock atomically.

    This is the core service function for staff stock recording.
    Creates an append-only StockMovement record.

    Args:
        product: Product instance
        movement_type: 'IN', 'OUT', 'SALE', 'ADJUSTMENT_IN', or 'ADJUSTMENT_OUT'
        quantity: Decimal quantity in the specified unit
        unit: Unit instance for the quantity
        reason_category: Optional reason (required for OUT)
        reason_notes: Optional notes (max 200 chars)
        user: CustomUser who recorded this movement
        reference_id: Optional reference ID

    Returns:
        StockMovement: The created movement record

    Raises:
        StockValidationError: If validation fails
        InsufficientStockError: If OUT/SALE/ADJUSTMENT_OUT would make stock negative
        UnitTypeMismatchError: If unit types don't match
    """
    if movement_type not in ('IN', 'OUT', 'SALE', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT'):
        raise StockValidationError(
            f'Invalid movement type: {movement_type}. '
            f'Must be IN, OUT, SALE, ADJUSTMENT_IN, or ADJUSTMENT_OUT.'
        )

    quantity_decimal = _quantize_quantity(quantity)
    if quantity_decimal <= Decimal('0'):
        raise StockValidationError('Quantity must be positive.')

    if unit.unit_type != product.unit.unit_type:
        raise UnitTypeMismatchError(
            f'Unit type mismatch: {unit.name} ({unit.unit_type}) '
            f'cannot be used with {product.name} ({product.unit.unit_type}).'
        )

    quantity_in_product_unit = convert_quantity_between_units(
        quantity_decimal, unit, product.unit
    )

    with transaction.atomic():
        locked_product = Product.objects.select_for_update().get(pk=product.pk)

        if movement_type in ('OUT', 'SALE', 'ADJUSTMENT_OUT'):
            new_stock = _quantize_quantity(
                locked_product.stock_quantity - quantity_in_product_unit
            )
            if new_stock < Decimal('0'):
                raise InsufficientStockError(
                    f'Insufficient stock. Available: {locked_product.stock_quantity} '
                    f'{locked_product.unit.name}. Requested: {quantity_in_product_unit} '
                    f'{locked_product.unit.name}.'
                )
            locked_product.stock_quantity = new_stock
        else:
            # IN, ADJUSTMENT_IN increment stock
            locked_product.stock_quantity = _quantize_quantity(
                locked_product.stock_quantity + quantity_in_product_unit
            )

        locked_product.save(update_fields=['stock_quantity', 'updated_at'])

        movement = StockMovement.objects.create(
            product=locked_product,
            quantity=quantity_in_product_unit,
            unit_cost_snapshot=_snapshot_unit_cost(locked_product),
            movement_type=movement_type,
            reason_category=reason_category or None,
            reason_notes=reason_notes or None,
            recorded_by=user,
            reference_id=reference_id,
        )

    return movement


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
        StockValidationError: If quantity is not positive
    """
    return record_movement(
        product=product,
        movement_type='IN',
        quantity=quantity,
        unit=product.unit,
        reason_category=reason_category,
        reason_notes=reason_notes,
        user=user,
        reference_id=reference_id,
    )


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
        StockValidationError: If quantity is not positive
        InsufficientStockError: If would make stock negative
    """
    return record_movement(
        product=product,
        movement_type='OUT',
        quantity=quantity,
        unit=product.unit,
        reason_category=reason_category,
        reason_notes=reason_notes,
        user=user,
        reference_id=reference_id,
    )


def record_adjustment_in(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record positive stock adjustment (ADJUSTMENT_IN) and update product stock.

    Args:
        product: Product instance to adjust
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this adjustment
        reference_id: Optional reference (e.g., stock take ID)

    Returns:
        StockMovement: The created movement record

    Raises:
        StockValidationError: If quantity is not positive
    """
    return record_movement(
        product=product,
        movement_type='ADJUSTMENT_IN',
        quantity=quantity,
        unit=product.unit,
        reason_category=reason_category,
        reason_notes=reason_notes,
        user=user,
        reference_id=reference_id,
    )


def record_adjustment_out(product, quantity, reason_category, reason_notes, user, reference_id=None):
    """
    Record negative stock adjustment (ADJUSTMENT_OUT) and update product stock.

    Args:
        product: Product instance to adjust
        quantity: Decimal quantity in product's unit
        reason_category: One of StockMovement.REASON_CATEGORY_CHOICES
        reason_notes: Optional notes (do not include personal names)
        user: CustomUser who recorded this adjustment
        reference_id: Optional reference (e.g., stock take ID)

    Returns:
        StockMovement: The created movement record

    Raises:
        StockValidationError: If quantity is not positive
        InsufficientStockError: If adjustment would make stock negative
    """
    return record_movement(
        product=product,
        movement_type='ADJUSTMENT_OUT',
        quantity=quantity,
        unit=product.unit,
        reason_category=reason_category,
        reason_notes=reason_notes,
        user=user,
        reference_id=reference_id,
    )
