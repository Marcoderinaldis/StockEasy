from decimal import Decimal


def calculate_recipe_cost(recipe):
    """
    Returns the total ingredient cost for a recipe.
    Sums quantity * cost_per_unit for each RecipeIngredient.
    """
    total = Decimal('0.0000')
    for ri in recipe.recipe_ingredients.select_related('ingredient'):
        total += ri.quantity * ri.ingredient.cost_per_unit
    return total


def calculate_cost_per_portion(recipe):
    """
    Returns the cost per portion.
    Raises ValueError if portions is zero or not set.
    """
    if not recipe.portions or recipe.portions == 0:
        raise ValueError('Recipe must have at least one portion defined.')
    return calculate_recipe_cost(recipe) / Decimal(recipe.portions)


def suggest_selling_price(recipe, target_margin_pct):
    """
    Returns a suggested selling price per portion based on a target gross margin.
    target_margin_pct: integer or Decimal, e.g. 70 means 70% gross margin.
    Formula: selling_price = cost_per_portion / (1 - margin)
    """
    if not (0 < target_margin_pct < 100):
        raise ValueError('Target margin must be between 0 and 100.')
    margin = Decimal(str(target_margin_pct)) / Decimal('100')
    cost = calculate_cost_per_portion(recipe)
    return cost / (Decimal('1') - margin)
