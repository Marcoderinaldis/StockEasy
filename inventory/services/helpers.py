"""
Inventory service helpers and utilities.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .exceptions import StockValidationError

QUANTITY_PRECISION = Decimal('0.0001')


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
