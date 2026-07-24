"""
Order placement service functions.
"""

from decimal import Decimal

from django.db import transaction

from .exceptions import OrderError
from .helpers import _quantize_quantity
from .movements import record_movement


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
    from ..models import Order, OrderLine

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
