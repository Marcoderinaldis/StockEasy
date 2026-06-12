"""
Recipe service layer for StockEasy.

Provides recipe costing calculations with unit conversion support.
"""

from decimal import Decimal


def calculate_recipe_cost(recipe, product_prices=None):
    """
    Calculate the total cost for a recipe.

    Converts each RecipeIngredient quantity to the product's unit,
    then multiplies by the product's current purchase price.

    Args:
        recipe: Recipe instance to calculate cost for
        product_prices: Optional dict mapping product_id to unit_price.
                       If not provided, uses current PurchasePrice from database.

    Returns:
        Decimal: Total recipe cost

    Raises:
        ValueError: If unit conversion fails (incompatible unit types)
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")


def calculate_cost_per_yield(recipe, product_prices=None):
    """
    Calculate the cost per yield unit for a recipe.

    Args:
        recipe: Recipe instance
        product_prices: Optional dict mapping product_id to unit_price

    Returns:
        Decimal: Cost per yield unit

    Raises:
        ValueError: If yields_quantity is zero or negative
    """
    # TODO: Implement in Sprint 3
    raise NotImplementedError("To be implemented in Sprint 3")
