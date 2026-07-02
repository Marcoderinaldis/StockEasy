"""
Costing service layer for StockEasy.

Provides product and recipe costing calculations.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from inventory.models import PurchasePrice


class PriceValidationError(Exception):
    """Raised when price validation fails."""
    pass


def set_product_price(product, unit_price, user):
    """
    Set a new price for a product.

    This is APPEND-ONLY: existing prices are never edited or deleted.
    The current active price (effective_to=null) is closed by setting
    effective_to to now, and a new price row is created.

    Args:
        product: Product instance to set price for
        unit_price: New unit price (Decimal, str, int, or float)
        user: User creating the price

    Returns:
        PurchasePrice: The newly created active price

    Raises:
        PriceValidationError: If unit_price is not a positive Decimal
    """
    # Validate and quantize unit_price to 2 decimal places
    try:
        price_decimal = Decimal(str(unit_price))
    except (InvalidOperation, ValueError, TypeError):
        raise PriceValidationError("Price must be a valid number.")

    if price_decimal <= 0:
        raise PriceValidationError("Price must be positive.")

    # Quantize to 2 decimal places
    price_decimal = price_decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    with transaction.atomic():
        now = timezone.now()

        # Close all currently active prices for this product
        # (there should be one, but close all to be safe)
        PurchasePrice.objects.filter(
            product=product,
            effective_to__isnull=True
        ).update(effective_to=now)

        # Create new active price
        new_price = PurchasePrice.objects.create(
            product=product,
            unit_price=price_decimal,
            currency='GBP',
            created_by=user,
            effective_to=None,
        )

        return new_price


def calculate_product_cost(product):
    """
    Get the current cost per unit for a product.

    Returns the most recent active PurchasePrice for the product.
    An active price has effective_to=null.

    Args:
        product: Product instance to get cost for

    Returns:
        Decimal: Current unit price, or Decimal('0') if no active price exists
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def get_price_history(product, start_date=None, end_date=None):
    """
    Get purchase price history for a product.

    Args:
        product: Product instance
        start_date: Optional start date filter (inclusive)
        end_date: Optional end date filter (inclusive)

    Returns:
        QuerySet: PurchasePrice records ordered by effective_from descending
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def suggest_selling_price(recipe, target_margin_percent):
    """
    Suggest a selling price based on target gross margin.

    Formula: selling_price = cost_per_yield / (1 - margin)

    Args:
        recipe: Recipe instance
        target_margin_percent: Target margin as percentage (e.g., 70 for 70%)

    Returns:
        Decimal: Suggested selling price per yield unit

    Raises:
        ValueError: If margin is not between 0 and 100 (exclusive)
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")
