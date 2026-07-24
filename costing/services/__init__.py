"""
Costing service layer for StockEasy.

Provides product and recipe costing calculations.
"""

from .exceptions import (
    PriceValidationError,
    MissingPriceError,
)
from .prices import (
    MONEY_PRECISION,
    _quantize_money,
    set_product_price,
    calculate_product_cost,
    get_price_history,
)
from .recipes import (
    RecipeLineCost,
    RecipeCost,
    RecipeMargin,
    SuggestedPrice,
    calculate_recipe_cost,
    calculate_recipe_margin,
    suggest_selling_price,
)

__all__ = [
    # Exceptions
    'PriceValidationError',
    'MissingPriceError',
    # Prices
    'MONEY_PRECISION',
    '_quantize_money',
    'set_product_price',
    'calculate_product_cost',
    'get_price_history',
    # Recipes
    'RecipeLineCost',
    'RecipeCost',
    'RecipeMargin',
    'SuggestedPrice',
    'calculate_recipe_cost',
    'calculate_recipe_margin',
    'suggest_selling_price',
]
