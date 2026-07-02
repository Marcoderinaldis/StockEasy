"""
Costing service layer for StockEasy.

Provides product and recipe costing calculations.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from inventory.models import PurchasePrice
from inventory.services import convert_quantity_between_units, _quantize_quantity

MONEY_PRECISION = Decimal('0.01')


class PriceValidationError(Exception):
    """Raised when price validation fails."""
    pass


class MissingPriceError(Exception):
    """Raised when a product has no active price."""

    def __init__(self, product):
        self.product = product
        super().__init__(f'No active price for product: {product}')


def _quantize_money(value):
    """
    Quantize a Decimal to money precision (2 decimal places).

    Args:
        value: Numeric value to quantize

    Returns:
        Decimal: Value quantized to 2 decimal places

    Raises:
        PriceValidationError: If value cannot be converted to Decimal
    """
    try:
        decimal_value = Decimal(str(value))
        return decimal_value.quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as e:
        raise PriceValidationError(f'Invalid money value: {value}') from e


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

    Returns the unit_price from the active PurchasePrice for the product.
    An active price has effective_to=null.

    Args:
        product: Product instance to get cost for

    Returns:
        Decimal: Current unit price (per product.unit)

    Raises:
        MissingPriceError: If no active price exists for this product
    """
    price = product.current_price
    if price is None:
        raise MissingPriceError(product)
    return price.unit_price


@dataclass
class RecipeLineCost:
    """Cost calculation result for a single recipe ingredient."""
    ingredient_id: int
    product_id: int
    product_name: str
    quantity: Decimal                       # original ingredient qty
    ingredient_unit_name: str
    product_unit_name: str
    quantity_in_product_unit: Decimal | None
    unit_cost: Decimal | None               # per product unit
    raw_line_cost: Decimal | None           # unquantized
    line_cost: Decimal | None               # money 2dp
    issue: str | None                       # None | 'missing_price' | 'unit_mismatch'


@dataclass
class RecipeCost:
    """Cost calculation result for an entire recipe."""
    recipe_id: int
    recipe_name: str
    yields_quantity: Decimal
    yields_unit_name: str
    lines: list                             # list[RecipeLineCost]
    raw_total_cost: Decimal | None          # unquantized sum; None if incomplete
    total_cost: Decimal | None              # money 2dp; None if incomplete
    cost_per_yield_unit: Decimal | None     # money 2dp; None if incomplete or yield<=0
    is_complete: bool
    missing_price_products: list            # list[str] names
    unit_mismatch_products: list            # list[str] names


def calculate_recipe_cost(recipe):
    """
    Calculate the total cost for a recipe.

    Converts each RecipeIngredient quantity to the product's unit,
    then multiplies by the product's current purchase price.

    Fails SOFT on missing prices or unit mismatches — returns a RecipeCost
    with is_complete=False and the issues listed, so the page can still render.

    Args:
        recipe: Recipe instance to calculate cost for

    Returns:
        RecipeCost: Detailed cost breakdown with line-by-line costs
    """
    lines = []
    missing_price_products = []
    unit_mismatch_products = []

    ingredients = recipe.ingredients.select_related(
        'product', 'product__unit', 'unit'
    )

    for ing in ingredients:
        product = ing.product
        quantity = ing.quantity
        ingredient_unit = ing.unit
        product_unit = product.unit

        # Initialize line values
        qty_in_product_unit = None
        unit_cost = None
        raw_line_cost = None
        line_cost = None
        issue = None

        try:
            # Step 1: Convert quantity to product unit
            qty_in_product_unit = convert_quantity_between_units(
                quantity, ingredient_unit, product_unit
            )

            # Step 2: Get product unit cost (may raise MissingPriceError)
            unit_cost = calculate_product_cost(product)

            # Step 3: Calculate line cost
            raw_line_cost = qty_in_product_unit * unit_cost
            line_cost = _quantize_money(raw_line_cost)

        except ValueError:
            # Unit type mismatch from convert_quantity_between_units
            # qty_in_product_unit stays None (conversion failed)
            issue = 'unit_mismatch'
            unit_mismatch_products.append(product.name)

        except MissingPriceError:
            # qty_in_product_unit may have succeeded, keep it
            # unit_cost/raw_line_cost/line_cost stay None
            issue = 'missing_price'
            missing_price_products.append(product.name)

        line = RecipeLineCost(
            ingredient_id=ing.id,
            product_id=product.id,
            product_name=product.name,
            quantity=quantity,
            ingredient_unit_name=ingredient_unit.name,
            product_unit_name=product_unit.name,
            quantity_in_product_unit=qty_in_product_unit,
            unit_cost=unit_cost,
            raw_line_cost=raw_line_cost,
            line_cost=line_cost,
            issue=issue,
        )
        lines.append(line)

    # Determine if all lines are complete
    is_complete = all(line.issue is None for line in lines)

    if is_complete and lines:
        # Sum raw (unquantized) line costs for maximum precision
        raw_total_cost = sum(line.raw_line_cost for line in lines)
        total_cost = _quantize_money(raw_total_cost)

        # Calculate cost per yield unit
        if recipe.yields_quantity > 0:
            cost_per_yield_unit = _quantize_money(raw_total_cost / recipe.yields_quantity)
        else:
            # Zero yield is a data bug, not a pricing gap
            cost_per_yield_unit = None
    else:
        raw_total_cost = None
        total_cost = None
        cost_per_yield_unit = None

    return RecipeCost(
        recipe_id=recipe.id,
        recipe_name=recipe.name,
        yields_quantity=recipe.yields_quantity,
        yields_unit_name=recipe.yields_unit.name,
        lines=lines,
        raw_total_cost=raw_total_cost,
        total_cost=total_cost,
        cost_per_yield_unit=cost_per_yield_unit,
        is_complete=is_complete,
        missing_price_products=missing_price_products,
        unit_mismatch_products=unit_mismatch_products,
    )


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
