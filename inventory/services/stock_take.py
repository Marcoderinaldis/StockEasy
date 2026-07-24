"""
Stock take service functions.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from ..models import Product
from .exceptions import StockValidationError
from .helpers import _quantize_quantity
from .movements import record_adjustment_in, record_adjustment_out


@dataclass
class StockTakeLinePreview:
    """Preview of a single stock take line's discrepancy."""
    product_id: int
    product_name: str
    unit_name: str
    system_quantity_snapshot: Decimal
    counted_quantity: Optional[Decimal]
    discrepancy: Optional[Decimal]
    movement_type: Optional[str]  # 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', or None


@dataclass
class StockTakePreview:
    """Preview of a stock take's discrepancies and readiness."""
    lines: List[StockTakeLinePreview]
    total_lines: int
    counted_lines: int
    uncounted_lines: int
    lines_with_discrepancy: int
    is_ready_to_apply: bool


def start_stock_take(user, reference=None, notes=None):
    """
    Open a new stock take and snapshot the system quantity of every active product.

    Creates the StockTake and one StockTakeLine per active product with
    system_quantity_snapshot frozen at this moment. Records NO stock movement and
    changes NO stock — counting is a separate phase from applying.

    Args:
        user: CustomUser who is performing the count
        reference: Optional free-text label (e.g., a count reference or date)
        notes: Optional notes for the stock take

    Returns:
        StockTake: The created stock take with lines for all active products

    Raises:
        StockValidationError: If there are no active products
    """
    from ..models import StockTake, StockTakeLine

    with transaction.atomic():
        # Get all active products
        active_products = list(Product.objects.filter(is_active=True))

        if not active_products:
            raise StockValidationError('No active products to count.')

        # Create the stock take
        stock_take = StockTake.objects.create(
            reference=reference,
            notes=notes,
            counted_by=user,
        )

        # Bulk create lines for all active products
        lines = [
            StockTakeLine(
                stock_take=stock_take,
                product=product,
                system_quantity_snapshot=_quantize_quantity(product.stock_quantity),
                counted_quantity=None,
            )
            for product in active_products
        ]
        StockTakeLine.objects.bulk_create(lines)

    return stock_take


def record_count(line, counted_quantity):
    """
    Record the physically counted quantity for one stock take line.

    Does not change stock; the count is only applied when the stock take is applied.

    Args:
        line: StockTakeLine instance to record the count for
        counted_quantity: The physically counted quantity (non-negative Decimal)

    Returns:
        StockTakeLine: The updated line

    Raises:
        StockValidationError: If the stock take is already applied or quantity is negative
    """
    # Validate stock take is not already applied
    if line.stock_take.is_applied:
        raise StockValidationError('Cannot record count: stock take has already been applied.')

    # Quantize and validate
    qty = _quantize_quantity(counted_quantity)
    if qty < Decimal('0'):
        raise StockValidationError('Counted quantity cannot be negative.')

    line.counted_quantity = qty
    line.save(update_fields=['counted_quantity'])

    return line


def record_counts(stock_take, counts):
    """
    Record multiple counted quantities for a stock take in one transaction.

    Args:
        stock_take: StockTake instance
        counts: Dict mapping product_id (int) to counted_quantity (Decimal),
                or an iterable of (product_id, counted_quantity) tuples

    Returns:
        List[StockTakeLine]: The updated lines

    Raises:
        StockValidationError: If the stock take is already applied, a quantity is
            negative, or a product_id has no corresponding line in this stock take
    """
    # Validate stock take is not already applied
    if stock_take.is_applied:
        raise StockValidationError('Cannot record counts: stock take has already been applied.')

    # Normalize input to dict
    if hasattr(counts, 'items'):
        counts_dict = dict(counts)
    else:
        counts_dict = dict(counts)

    with transaction.atomic():
        # Fetch all lines for this stock take, indexed by product_id
        lines_by_product = {
            line.product_id: line
            for line in stock_take.lines.select_related('product')
        }

        updated_lines = []
        for product_id, counted_quantity in counts_dict.items():
            if product_id not in lines_by_product:
                raise StockValidationError(
                    f'No line found for product ID {product_id} in this stock take.'
                )

            line = lines_by_product[product_id]
            qty = _quantize_quantity(counted_quantity)
            if qty < Decimal('0'):
                raise StockValidationError(
                    f'Counted quantity cannot be negative for product "{line.product.name}".'
                )

            line.counted_quantity = qty
            line.save(update_fields=['counted_quantity'])
            updated_lines.append(line)

    return updated_lines


def preview_stock_take(stock_take):
    """
    Return the discrepancies a stock take would apply, without changing anything.

    This backs the confirmation step: a manager sees exactly what will be adjusted
    before committing to it. Read-only, no mutation. Product-level only.

    Args:
        stock_take: StockTake instance to preview

    Returns:
        StockTakePreview: Structured result with per-line discrepancies and summary
    """
    lines = stock_take.lines.select_related('product', 'product__unit').order_by('product__name')

    previews = []
    counted_lines = 0
    uncounted_lines = 0
    lines_with_discrepancy = 0

    for line in lines:
        if line.counted_quantity is not None:
            counted_lines += 1
            discrepancy = _quantize_quantity(
                line.counted_quantity - line.system_quantity_snapshot
            )
            if discrepancy > Decimal('0'):
                movement_type = 'ADJUSTMENT_IN'
                lines_with_discrepancy += 1
            elif discrepancy < Decimal('0'):
                movement_type = 'ADJUSTMENT_OUT'
                lines_with_discrepancy += 1
            else:
                movement_type = None  # Zero discrepancy, no movement
        else:
            uncounted_lines += 1
            discrepancy = None
            movement_type = None

        previews.append(StockTakeLinePreview(
            product_id=line.product_id,
            product_name=line.product.name,
            unit_name=line.product.unit.name,
            system_quantity_snapshot=line.system_quantity_snapshot,
            counted_quantity=line.counted_quantity,
            discrepancy=discrepancy,
            movement_type=movement_type,
        ))

    total_lines = counted_lines + uncounted_lines
    is_ready = uncounted_lines == 0 and total_lines > 0

    return StockTakePreview(
        lines=previews,
        total_lines=total_lines,
        counted_lines=counted_lines,
        uncounted_lines=uncounted_lines,
        lines_with_discrepancy=lines_with_discrepancy,
        is_ready_to_apply=is_ready,
    )


def apply_stock_take(stock_take, user):
    """
    Apply a stock take: write an ADJUSTMENT movement for every non-zero discrepancy
    and mark the stock take applied.

    The discrepancy is applied as a delta against the snapshot taken when the line was
    counted, so any legitimate movement recorded between counting and applying is
    preserved rather than overwritten.

    All-or-nothing: if any adjustment cannot be written (for example an ADJUSTMENT_OUT
    that would take stock negative), nothing is applied and the stock take remains a
    draft.

    Args:
        stock_take: StockTake instance to apply
        user: CustomUser who is applying the stock take

    Returns:
        dict: Result with 'stock_take', 'adjustments_in', 'adjustments_out',
              'zero_discrepancies' counts

    Raises:
        StockValidationError: If stock take is already applied or has uncounted lines
        InsufficientStockError: If any ADJUSTMENT_OUT would make stock negative
            (entire application is rolled back)
    """
    # Validate not already applied
    if stock_take.is_applied:
        raise StockValidationError('Stock take has already been applied.')

    # Validate all lines have been counted
    uncounted_count = stock_take.lines.filter(counted_quantity__isnull=True).count()
    if uncounted_count > 0:
        raise StockValidationError(
            f'Cannot apply: {uncounted_count} line(s) have not been counted.'
        )

    adjustments_in = 0
    adjustments_out = 0
    zero_discrepancies = 0
    reference = f'stocktake-{stock_take.pk}'
    reason_notes = f'Stock take #{stock_take.pk}'

    with transaction.atomic():
        lines = stock_take.lines.select_related('product', 'product__unit')

        for line in lines:
            discrepancy = _quantize_quantity(
                line.counted_quantity - line.system_quantity_snapshot
            )

            # Store the discrepancy on the line
            line.discrepancy = discrepancy
            line.save(update_fields=['discrepancy'])

            if discrepancy == Decimal('0'):
                zero_discrepancies += 1
                continue  # Nothing to reconcile

            if discrepancy > Decimal('0'):
                # Found more than expected: ADJUSTMENT_IN
                record_adjustment_in(
                    product=line.product,
                    quantity=discrepancy,
                    reason_category='Stock take adjustment',
                    reason_notes=reason_notes,
                    user=user,
                    reference_id=reference,
                )
                adjustments_in += 1
            else:
                # Found less than expected: ADJUSTMENT_OUT
                record_adjustment_out(
                    product=line.product,
                    quantity=abs(discrepancy),
                    reason_category='Stock take adjustment',
                    reason_notes=reason_notes,
                    user=user,
                    reference_id=reference,
                )
                adjustments_out += 1

        # Mark as applied
        stock_take.applied_at = timezone.now()
        stock_take.save(update_fields=['applied_at'])

    return {
        'stock_take': stock_take,
        'adjustments_in': adjustments_in,
        'adjustments_out': adjustments_out,
        'zero_discrepancies': zero_discrepancies,
    }
