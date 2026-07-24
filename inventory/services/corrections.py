"""
Stock movement void and correction functions.
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


# Movement types that can be voided
VOIDABLE_MOVEMENT_TYPES = ('IN', 'OUT', 'WASTE')


def is_voided(movement):
    """
    Check if a movement has been voided.

    A movement is voided if a VOID movement points at it via the voids FK.
    This is derived from the ledger — no mutable boolean flag.

    Args:
        movement: StockMovement instance to check

    Returns:
        bool: True if the movement has been voided
    """
    try:
        return movement.voided_by is not None
    except StockMovement.DoesNotExist:
        return False


def void_movement(movement, reason_notes, user):
    """
    Void an existing stock movement by creating a VOID movement.

    StockMovement is append-only, so this creates a new VOID movement
    that reverses the effect of the original movement and links to it.

    Double-void prevention is enforced at both the service layer (pre-check)
    and the database layer (OneToOne constraint on voids FK).

    Args:
        movement: StockMovement instance to void
        reason_notes: Reason for voiding (required - mandatory justification)
        user: CustomUser who is voiding the movement

    Returns:
        StockMovement: The created VOID movement record

    Raises:
        StockValidationError: If movement cannot be voided (already voided,
            is a VOID, unsupported type, or missing justification)
        InsufficientStockError: If voiding would make stock negative
    """
    # Validate justification is provided (mandatory)
    if not reason_notes or not reason_notes.strip():
        raise StockValidationError('Justification is required when voiding a movement.')

    # Validate movement type is not VOID
    if movement.movement_type == 'VOID':
        raise StockValidationError('Cannot void a void.')

    # Validate movement type is voidable
    if movement.movement_type not in VOIDABLE_MOVEMENT_TYPES:
        raise StockValidationError('This movement type cannot be voided.')

    # Pre-check if already voided (service-level check before DB constraint)
    if is_voided(movement):
        raise StockValidationError('This movement has already been voided.')

    # Get the original quantity (already stored in product units on the ledger)
    original_quantity = _quantize_quantity(movement.quantity)

    with transaction.atomic():
        # Re-fetch and lock the product row
        locked_product = Product.objects.select_for_update().get(pk=movement.product_id)

        # Re-fetch the movement inside the transaction to ensure consistency
        locked_movement = StockMovement.objects.select_for_update().get(pk=movement.pk)

        # Double-check voided status inside transaction
        if is_voided(locked_movement):
            raise StockValidationError('This movement has already been voided.')

        # Compute the reversal effect on stock
        # IN added stock -> reversal SUBTRACTS
        # OUT subtracted stock -> reversal ADDS
        # WASTE subtracted stock -> reversal ADDS
        if locked_movement.movement_type == 'IN':
            # Voiding an IN: subtract the quantity back
            new_stock = _quantize_quantity(
                locked_product.stock_quantity - original_quantity
            )
            if new_stock < Decimal('0'):
                raise InsufficientStockError(
                    'Cannot void: stock has since been consumed and would go negative. '
                    f'Available: {locked_product.stock_quantity} {locked_product.unit.name}. '
                    f'Required to reverse: {original_quantity} {locked_product.unit.name}.'
                )
        else:
            # Voiding an OUT or WASTE: add the quantity back
            new_stock = _quantize_quantity(
                locked_product.stock_quantity + original_quantity
            )

        # Apply the reversal to product stock
        locked_product.stock_quantity = new_stock
        locked_product.save(update_fields=['stock_quantity', 'updated_at'])

        # Create the VOID movement linked to the original
        void_record = StockMovement.objects.create(
            product=locked_product,
            quantity=original_quantity,
            unit_cost_snapshot=locked_movement.unit_cost_snapshot,
            movement_type='VOID',
            reason_category='Void—entered in error',
            reason_notes=reason_notes.strip(),
            recorded_by=user,
            voids=locked_movement,
        )

    return void_record


def is_corrected(movement):
    """
    Check if a movement has been corrected.

    A movement is corrected if a replacement movement points at it via the corrects FK.
    This is derived from the ledger — no mutable boolean flag.

    Args:
        movement: StockMovement instance to check

    Returns:
        bool: True if the movement has been corrected
    """
    return movement.corrected_by.exists()


# Movement types that can be corrected (same as voidable)
CORRECTABLE_MOVEMENT_TYPES = ('IN', 'OUT', 'WASTE')


def correct_movement(
    original,
    corrected_quantity,
    corrected_unit,
    corrected_reason_category,
    corrected_notes,
    justification,
    user,
):
    """
    Correct an existing stock movement by creating a VOID and a replacement.

    A correction fixes a movement that was entered with the wrong QUANTITY
    (and optionally wrong reason/note). Same product, same movement_type.

    CRITICAL: Validates FINAL net stock, NOT intermediate steps.
    This avoids falsely blocking valid corrections (e.g., correcting IN 30 to 25
    after 10 units were consumed: intermediate would be -10 but net result is +15).

    Net delta by type (same type old->new):
        IN:    net = corrected_qty - original_qty
        OUT:   net = original_qty - corrected_qty
        WASTE: net = original_qty - corrected_qty

    Args:
        original: StockMovement instance to correct
        corrected_quantity: New quantity (positive Decimal)
        corrected_unit: Unit instance for the corrected quantity
        corrected_reason_category: Optional reason category for replacement
        corrected_notes: Optional notes for replacement (max 200 chars)
        justification: Reason for correction (required)
        user: CustomUser who is making the correction

    Returns:
        StockMovement: The replacement movement record

    Raises:
        StockValidationError: If correction validation fails
        InsufficientStockError: If FINAL stock would go negative
        UnitTypeMismatchError: If unit types don't match
    """
    # Validate justification is provided (mandatory)
    if not justification or not justification.strip():
        raise StockValidationError('Justification is required when correcting a movement.')

    # Validate corrected quantity is positive
    corrected_quantity_decimal = _quantize_quantity(corrected_quantity)
    if corrected_quantity_decimal <= Decimal('0'):
        raise StockValidationError('Corrected quantity must be positive.')

    # Validate movement type is not VOID
    if original.movement_type == 'VOID':
        raise StockValidationError('Cannot correct a void.')

    # Validate movement type is correctable
    if original.movement_type not in CORRECTABLE_MOVEMENT_TYPES:
        raise StockValidationError('This movement type cannot be corrected.')

    # Pre-check if already voided (service-level check)
    if is_voided(original):
        raise StockValidationError('This movement has already been voided.')

    # Pre-check if already corrected (service-level check)
    if is_corrected(original):
        raise StockValidationError('This movement has already been corrected.')

    # Validate unit type matches product's unit type
    if corrected_unit.unit_type != original.product.unit.unit_type:
        raise UnitTypeMismatchError(
            f'Unit type mismatch: {corrected_unit.name} ({corrected_unit.unit_type}) '
            f'cannot be used with {original.product.name} ({original.product.unit.unit_type}).'
        )

    # Convert corrected quantity to product unit
    corrected_qty_in_product_unit = convert_quantity_between_units(
        corrected_quantity_decimal, corrected_unit, original.product.unit
    )

    # Get the original quantity (already stored in product units on the ledger)
    original_quantity = _quantize_quantity(original.quantity)

    with transaction.atomic():
        # Re-fetch and lock the product row
        locked_product = Product.objects.select_for_update().get(pk=original.product_id)

        # Re-fetch the original movement inside the transaction
        locked_original = StockMovement.objects.select_for_update().get(pk=original.pk)

        # Double-check voided/corrected status inside transaction
        if is_voided(locked_original):
            raise StockValidationError('This movement has already been voided.')
        if is_corrected(locked_original):
            raise StockValidationError('This movement has already been corrected.')

        # Compute NET stock change (FINAL validation, not intermediate)
        # IN:    net = corrected_qty - original_qty (more IN raises stock, less lowers it)
        # OUT:   net = original_qty - corrected_qty (more OUT lowers stock, less raises it)
        # WASTE: net = original_qty - corrected_qty (same as OUT)
        if locked_original.movement_type == 'IN':
            net_delta = _quantize_quantity(
                corrected_qty_in_product_unit - original_quantity
            )
        else:
            # OUT or WASTE
            net_delta = _quantize_quantity(
                original_quantity - corrected_qty_in_product_unit
            )

        # Calculate and validate FINAL stock (not intermediate)
        new_stock = _quantize_quantity(locked_product.stock_quantity + net_delta)

        if new_stock < Decimal('0'):
            raise InsufficientStockError(
                f'Cannot correct: final stock would go negative. '
                f'Current: {locked_product.stock_quantity} {locked_product.unit.name}. '
                f'Net change: {net_delta} {locked_product.unit.name}. '
                f'Final would be: {new_stock} {locked_product.unit.name}.'
            )

        # Apply the net change to product stock (single update)
        locked_product.stock_quantity = new_stock
        locked_product.save(update_fields=['stock_quantity', 'updated_at'])

        # Create the VOID movement linked to the original (marks it voided)
        void_record = StockMovement.objects.create(
            product=locked_product,
            quantity=original_quantity,
            unit_cost_snapshot=locked_original.unit_cost_snapshot,
            movement_type='VOID',
            reason_category='Void—entered in error',
            reason_notes=justification.strip(),
            recorded_by=user,
            voids=locked_original,
        )

        # Create the REPLACEMENT movement (same product, same type, corrected values)
        replacement = StockMovement.objects.create(
            product=locked_product,
            quantity=corrected_qty_in_product_unit,
            unit_cost_snapshot=_snapshot_unit_cost(locked_product),
            movement_type=locked_original.movement_type,
            reason_category=corrected_reason_category or None,
            reason_notes=corrected_notes or None,
            recorded_by=user,
            corrects=locked_original,
        )

    return replacement
