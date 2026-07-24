"""
Waste recording service functions (write operations).
"""

from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

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
from ..models import WasteRecord


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MONEY_PRECISION = Decimal('0.01')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _quantize_money(value):
    """
    Quantize a Decimal to money precision (2 decimal places, half-up rounding).

    Args:
        value: Numeric value to quantize (Decimal, int, float, or str)

    Returns:
        Decimal: Value quantized to 2 decimal places

    Raises:
        ValueError: If value cannot be converted to Decimal
    """
    try:
        decimal_value = Decimal(str(value))
        return decimal_value.quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
    except Exception as e:
        raise ValueError(f'Invalid money value: {value}') from e


# ---------------------------------------------------------------------------
# Waste recording (write operations)
# ---------------------------------------------------------------------------

def record_waste(product, quantity, unit, waste_category, user, notes=None,
                 reference_id=None):
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
        reference_id: Optional reference string for grouping movements (max 50 chars)

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
            reference_id=reference_id,
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


def record_dish_waste(recipe, portions, waste_category, user, notes=None,
                      ingredients=None):
    """
    Record waste of a prepared dish, or of a preparation that was ruined before
    completion.

    A whole dish (ingredients=None) wastes every ingredient of the recipe, scaled
    to the number of portions. A partial loss (ingredients=[...]) wastes only the
    ingredients that had already been committed — for example a preparation
    spoiled early, where only some ingredients were in the pan.

    All resulting WASTE movements share one reference_id so the group can be
    identified. All-or-nothing: if any ingredient is short or has an incompatible
    unit, nothing is written.

    Limitation: voiding is per movement. Voiding one movement of a dish waste
    reverses only that ingredient; a group void is not implemented.

    Ingredients with a scaled quantity of zero or less are skipped (no movement
    created). This can occur with very small ingredient quantities and few
    portions.

    Args:
        recipe: Recipe instance to waste ingredients from
        portions: Number of portions wasted (positive integer)
        waste_category: One of StockMovement.REASON_CATEGORY_CHOICES (required)
        user: CustomUser who recorded this waste
        notes: Optional notes (do not include personal names)
        ingredients: Optional list of RecipeIngredient instances to waste. If
                     None, all recipe ingredients are wasted. If provided, must
                     be non-empty and all must belong to the given recipe.

    Returns:
        list[WasteRecord]: List of created WasteRecord objects, one per ingredient
                           that had a positive scaled quantity.

    Raises:
        StockValidationError: If validation fails (invalid portions, zero yield,
                              missing category, empty ingredients list, ingredient
                              not belonging to recipe, recipe has no ingredients).
        InsufficientStockError: If any ingredient is short (whole operation rolls
                                back).
        UnitTypeMismatchError: If any ingredient unit cannot convert to product
                               unit (whole operation rolls back).
    """
    # Validate portions is a positive integer
    if not isinstance(portions, int) or portions < 1:
        raise StockValidationError(
            f'Portions must be a positive integer, got {portions}.'
        )

    # Validate recipe has positive yield
    if recipe.yields_quantity <= 0:
        raise StockValidationError(
            f'Recipe "{recipe.name}" has invalid yield ({recipe.yields_quantity}).'
        )

    # Validate waste_category is provided
    if not waste_category or not waste_category.strip():
        raise StockValidationError('Waste category is required.')

    # Validate ingredients parameter
    if ingredients is not None:
        if not ingredients:
            raise StockValidationError('Ingredients list cannot be empty.')
        # Check every ingredient belongs to this recipe
        for ing in ingredients:
            if ing.recipe_id != recipe.pk:
                raise StockValidationError(
                    f'Ingredient "{ing.product.name}" does not belong to recipe '
                    f'"{recipe.name}".'
                )
        target = ingredients
    else:
        # Use all recipe ingredients
        target = list(recipe.ingredients.select_related(
            'product', 'product__unit', 'unit'
        ))
        if not target:
            raise StockValidationError(
                f'Recipe "{recipe.name}" has no ingredients.'
            )

    # Generate unique reference for grouping movements
    reference = f'dish-waste-{uuid4().hex[:12]}'

    # Calculate scale factor
    scale = Decimal(portions) / recipe.yields_quantity

    # All-or-nothing: one outer transaction
    with transaction.atomic():
        records = []
        for ing in target:
            qty = _quantize_quantity(ing.quantity * scale)

            # Skip ingredients with zero or negative scaled quantity
            if qty <= Decimal('0'):
                continue

            # record_waste handles locking, negative-stock block, cost snapshot.
            # InsufficientStockError or UnitTypeMismatchError propagate out,
            # causing the outer atomic to roll back the entire dish waste.
            waste_record = record_waste(
                product=ing.product,
                quantity=qty,
                unit=ing.unit,
                waste_category=waste_category,
                user=user,
                notes=notes,
                reference_id=reference,
            )
            records.append(waste_record)

    return records
