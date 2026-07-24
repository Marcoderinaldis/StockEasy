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


class OrderError(StockValidationError):
    """Raised when order placement validation fails."""
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


def _snapshot_unit_cost(product):
    """
    Return the current unit price for a product, frozen for a stock movement.

    Reads the product's active price at call time. Returns None when no active
    price exists — a movement must never be blocked because a price is missing.
    """
    price = product.current_price
    return price.unit_price if price is not None else None


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


# Movement types that can be voided
VOIDABLE_MOVEMENT_TYPES = ('IN', 'OUT', 'WASTE')


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


def place_order(lines_data, user, reference=None, notes=None):
    """
    Place an order and atomically deplete recipe ingredients from stock via SALE
    movements. All-or-nothing: if ANY ingredient is short (or has a unit-type
    mismatch), the whole order is rolled back and nothing is written.

    Args:
        lines_data: Iterable of (recipe, portions) tuples where portions is a
                    positive int representing the number of dishes ordered.
        user: CustomUser placing the order.
        reference: Optional free-text label (e.g., table number).
        notes: Optional order notes.

    Returns:
        Order: The created Order instance (with lines and SALE movements committed).

    Raises:
        OrderError: If input validation fails (empty order, zero portions, recipe
                    with no ingredients, invalid yield).
        InsufficientStockError: If any ingredient is short (whole order rolled back).
        UnitTypeMismatchError: If any ingredient unit cannot convert to product unit
                               (whole order rolled back).
    """
    from .models import Order, OrderLine

    # Convert to list for validation (handles generators)
    lines_list = list(lines_data)

    # Validate non-empty
    if not lines_list:
        raise OrderError('Order must have at least one line.')

    # Validate each line before touching stock
    for recipe, portions in lines_list:
        if not isinstance(portions, int) or portions < 1:
            raise OrderError(
                f'Portions must be a positive integer, got {portions} for {recipe.name}.'
            )
        if recipe.yields_quantity <= 0:
            raise OrderError(
                f'Recipe "{recipe.name}" has invalid yield ({recipe.yields_quantity}).'
            )
        if not recipe.ingredients.exists():
            raise OrderError(
                f'Recipe "{recipe.name}" has no ingredients.'
            )

    # All-or-nothing: outer atomic wraps the entire order
    with transaction.atomic():
        order = Order.objects.create(
            placed_by=user,
            reference=reference,
            notes=notes,
        )

        for recipe, portions in lines_list:
            # Create order line with selling price snapshot
            OrderLine.objects.create(
                order=order,
                recipe=recipe,
                quantity=portions,
                unit_selling_price_snapshot=recipe.selling_price,  # may be None
            )

            # Scale factor: portions ordered / total yield
            scale = Decimal(portions) / recipe.yields_quantity

            # Deplete each ingredient
            for ing in recipe.ingredients.select_related('product', 'product__unit', 'unit'):
                deplete_qty = _quantize_quantity(ing.quantity * scale)

                # record_movement handles locking, negative-stock block, cost snapshot.
                # InsufficientStockError or UnitTypeMismatchError propagate out,
                # causing the outer atomic to roll back the entire order.
                record_movement(
                    product=ing.product,
                    movement_type='SALE',
                    quantity=deplete_qty,
                    unit=ing.unit,
                    user=user,
                    reference_id=f'order-{order.pk}',
                )

    return order
