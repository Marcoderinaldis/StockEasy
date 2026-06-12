"""
Costing service layer for StockEasy.

Provides product and recipe costing calculations.
"""

from decimal import Decimal


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
