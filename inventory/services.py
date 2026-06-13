"""
Inventory service layer for StockEasy.

All stock mutations MUST go through these service functions.
Direct model updates to Product.stock_quantity are NEVER allowed.
StockMovement is append-only; no updates or deletes ever.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import Product, StockMovement, Unit

QUANTITY_PRECISION = Decimal('0.0001')


class StockValidationError(Exception):
    """Raised when stock operation validation fails."""
    pass


class InsufficientStockError(StockValidationError):
    """Raised when OUT would make stock negative."""
    pass


class UnitTypeMismatchError(StockValidationError):
    """Raised when unit types do not match."""
    pass


def _quantize_quantity(value):
    """
    Quantize a Decimal to the precision used by quantity fields (4 decimal places).

    Handles invalid Decimal conversion safely.
    """
    try:
        decimal_value = Decimal(str(value))
        return decimal_value.quantize(QUANTITY_PRECISION, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as e:
        raise StockValidationError(f'Invalid quantity value: {value}') from e


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
        Decimal: The converted quantity, quantized to field precision

    Raises:
        ValueError: If unit types do not match
    """
    if from_unit.unit_type != to_unit.unit_type:
        raise ValueError(
            f'Cannot convert between different unit types: '
            f'{from_unit.unit_type} and {to_unit.unit_type}'
        )

    if from_unit.id == to_unit.id:
        return _quantize_quantity(quantity)

    quantity_decimal = _quantize_quantity(quantity)
    quantity_in_base = quantity_decimal * from_unit.conversion_to_base
    converted_quantity = quantity_in_base / to_unit.conversion_to_base
    return _quantize_quantity(converted_quantity)


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
    Record a stock movement (IN or OUT) and update product stock atomically.

    This is the core service function for staff stock recording.
    Creates an append-only StockMovement record.

    Args:
        product: Product instance
        movement_type: 'IN' or 'OUT'
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
        InsufficientStockError: If OUT would make stock negative
        UnitTypeMismatchError: If unit types don't match
    """
    if movement_type not in ('IN', 'OUT'):
        raise StockValidationError(
            f'Invalid movement type: {movement_type}. Must be IN or OUT.'
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

        if movement_type == 'OUT':
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
            locked_product.stock_quantity = _quantize_quantity(
                locked_product.stock_quantity + quantity_in_product_unit
            )

        locked_product.save(update_fields=['stock_quantity', 'updated_at'])

        movement = StockMovement.objects.create(
            product=locked_product,
            quantity=quantity_in_product_unit,
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
    raise NotImplementedError("To be implemented in Unit 5")


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
    raise NotImplementedError("To be implemented in Unit 6")


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
    raise NotImplementedError("To be implemented in a future unit")


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
    raise NotImplementedError("To be implemented in a future unit")
