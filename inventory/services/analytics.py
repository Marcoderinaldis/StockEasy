"""
Variance analytics (read-only aggregation) over the movement ledger.

This module holds read-only analytics for theoretical-versus-actual usage variance.
The sibling modules (movements, corrections, orders, stock_take) handle mutation;
this module never writes data.

k-anonymity note: The re-identification risk here is LOWER than in waste analytics
(stock takes are performed by managers and the data is product-level, not linked to
front-line staff shifts). The small-cell suppression control is applied for
consistency of treatment across the codebase rather than because an equivalent risk
exists.

LOCAL EQUIVALENTS: K_ANON_MIN and _suppress_small_cells are defined locally rather
than imported from waste.services because waste.services imports from
inventory.services, so the reverse import would create a cycle. This duplication is
accepted and noted plainly.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum, Count, Q, F, DecimalField

from inventory.models import StockMovement


# ---------------------------------------------------------------------------
# Constants (local equivalents to avoid circular import)
# ---------------------------------------------------------------------------

K_ANON_MIN = 3

MONEY_PRECISION = Decimal('0.01')

ALLOWED_VARIANCE_DIMENSIONS = frozenset({'product'})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quantize_money(value):
    """
    Quantize a Decimal to money precision (2 decimal places, half-up rounding).
    """
    try:
        decimal_value = Decimal(str(value))
        return decimal_value.quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
    except Exception as e:
        raise ValueError(f'Invalid money value: {value}') from e


def _suppress_small_cells(rows, dimension_key, min_count=K_ANON_MIN):
    """
    Merge aggregation rows backed by fewer than min_count underlying movements into a
    single 'Suppressed (fewer than N events)' bucket, preserving summed totals so the
    grand total reconciles.

    Local copy to avoid circular import from waste.services.

    Args:
        rows: List of dicts from variance aggregation, each containing 'movement_count'
              and the dimension key.
        dimension_key: The key name for the dimension ('product_name').
        min_count: Minimum movement count threshold (default K_ANON_MIN).

    Returns:
        List of dicts with sub-threshold rows merged into a 'Suppressed' bucket.
    """
    passed = []
    suppressed_movement_count = 0
    suppressed_theoretical_qty = Decimal('0')
    suppressed_theoretical_value = Decimal('0')
    suppressed_waste_qty = Decimal('0')
    suppressed_waste_value = Decimal('0')
    suppressed_unexplained_qty = Decimal('0')
    suppressed_unexplained_value = Decimal('0')

    for row in rows:
        if row['movement_count'] >= min_count:
            passed.append(row)
        else:
            suppressed_movement_count += row['movement_count']
            suppressed_theoretical_qty += row.get('theoretical_qty') or Decimal('0')
            suppressed_theoretical_value += row.get('theoretical_value') or Decimal('0')
            suppressed_waste_qty += row.get('recorded_waste_qty') or Decimal('0')
            suppressed_waste_value += row.get('waste_value') or Decimal('0')
            suppressed_unexplained_qty += row.get('unexplained_qty') or Decimal('0')
            suppressed_unexplained_value += row.get('unexplained_value') or Decimal('0')

    if suppressed_movement_count > 0:
        # Compute variance_pct for suppressed bucket
        if suppressed_theoretical_qty and suppressed_theoretical_qty != Decimal('0'):
            suppressed_variance_pct = (
                suppressed_unexplained_qty / suppressed_theoretical_qty * 100
            )
            suppressed_variance_pct = _quantize_money(suppressed_variance_pct)
            suppressed_status = 'calculated'
        else:
            suppressed_variance_pct = None
            suppressed_status = 'no_theoretical_usage'

        passed.append({
            dimension_key: f'Suppressed (fewer than {min_count} events)',
            'unit_name': 'mixed',
            'movement_count': suppressed_movement_count,
            'theoretical_qty': suppressed_theoretical_qty,
            'recorded_waste_qty': suppressed_waste_qty,
            'unexplained_qty': suppressed_unexplained_qty,
            'variance_pct': suppressed_variance_pct,
            'status': suppressed_status,
            'theoretical_value': _quantize_money(suppressed_theoretical_value),
            'waste_value': _quantize_money(suppressed_waste_value),
            'unexplained_value': _quantize_money(suppressed_unexplained_value),
        })

    return passed


# ---------------------------------------------------------------------------
# Variance analytics functions
# ---------------------------------------------------------------------------

def usage_variance_by(dimension='product', date_from=None, date_to=None, product=None):
    """
    Aggregate theoretical-versus-actual usage variance from the movement ledger.

    Theoretical usage is what the recipes said should have been consumed for the orders
    placed (SALE movements). Recorded waste is loss that was explained at the time. What
    a physical count then finds missing or surplus, recorded as stock-take adjustments,
    is the UNEXPLAINED variance - the part no one accounted for.

    Read-only. Never groups or filters by user: this function accepts no user parameter
    and rejects any dimension other than those allowed, so per-person variance is
    impossible at code level.

    Implementation choice: Uses ONE pass with conditional aggregation (Sum with
    filter=Q(movement_type=...)) rather than four separate queries. This is more
    efficient - a single database round-trip - and keeps the aggregation logic atomic.

    Args:
        dimension: Must be 'product' (the only allowed grouping key). Anything else
                   raises ValueError - in particular 'recorded_by' is impossible by
                   design.
        date_from: Optional date filter (inclusive) on recorded_at.
        date_to: Optional date filter (inclusive) on recorded_at.
        product: Optional single Product instance filter.

    Returns:
        List of dicts, each containing:
            - 'product_name': Product name
            - 'unit_name': Product's unit name
            - 'movement_count': Total movement count for k-anonymity
            - 'theoretical_qty': Sum of SALE quantities (Decimal)
            - 'recorded_waste_qty': Sum of WASTE quantities (Decimal)
            - 'unexplained_qty': ADJUSTMENT_IN - ADJUSTMENT_OUT (Decimal, negative = shortfall)
            - 'variance_pct': unexplained_qty / theoretical_qty * 100, or None
            - 'status': 'calculated' or 'no_theoretical_usage'
            - 'theoretical_value': theoretical_qty * unit_cost_snapshot (Decimal, 2dp)
            - 'waste_value': recorded_waste_qty * unit_cost_snapshot (Decimal, 2dp)
            - 'unexplained_value': unexplained_qty * unit_cost_snapshot (Decimal, 2dp)

    Raises:
        ValueError: If dimension is not in ALLOWED_VARIANCE_DIMENSIONS.
    """
    if dimension not in ALLOWED_VARIANCE_DIMENSIONS:
        raise ValueError(
            f"Invalid dimension '{dimension}'. "
            f"Allowed dimensions: {sorted(ALLOWED_VARIANCE_DIMENSIONS)}. "
            "Per-person grouping is prohibited."
        )

    # Base queryset: non-voided movements of relevant types
    # We need SALE, WASTE, ADJUSTMENT_IN, ADJUSTMENT_OUT
    relevant_types = ['SALE', 'WASTE', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT']
    base_qs = StockMovement.objects.filter(
        movement_type__in=relevant_types,
        voided_by__isnull=True,
    )

    if date_from:
        base_qs = base_qs.filter(recorded_at__date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(recorded_at__date__lte=date_to)
    if product:
        base_qs = base_qs.filter(product=product)

    # Aggregate per product using conditional aggregation (ONE PASS)
    aggregated = base_qs.values(
        'product__id', 'product__name', 'product__unit__name'
    ).annotate(
        movement_count=Count('id'),
        # Quantities
        theoretical_qty=Sum(
            'quantity',
            filter=Q(movement_type='SALE'),
            default=Decimal('0')
        ),
        recorded_waste_qty=Sum(
            'quantity',
            filter=Q(movement_type='WASTE'),
            default=Decimal('0')
        ),
        adjustment_in_qty=Sum(
            'quantity',
            filter=Q(movement_type='ADJUSTMENT_IN'),
            default=Decimal('0')
        ),
        adjustment_out_qty=Sum(
            'quantity',
            filter=Q(movement_type='ADJUSTMENT_OUT'),
            default=Decimal('0')
        ),
        # Values (only where unit_cost_snapshot is not null)
        theoretical_value=Sum(
            F('quantity') * F('unit_cost_snapshot'),
            filter=Q(movement_type='SALE', unit_cost_snapshot__isnull=False),
            output_field=DecimalField(max_digits=18, decimal_places=6),
            default=Decimal('0')
        ),
        waste_value=Sum(
            F('quantity') * F('unit_cost_snapshot'),
            filter=Q(movement_type='WASTE', unit_cost_snapshot__isnull=False),
            output_field=DecimalField(max_digits=18, decimal_places=6),
            default=Decimal('0')
        ),
        adjustment_in_value=Sum(
            F('quantity') * F('unit_cost_snapshot'),
            filter=Q(movement_type='ADJUSTMENT_IN', unit_cost_snapshot__isnull=False),
            output_field=DecimalField(max_digits=18, decimal_places=6),
            default=Decimal('0')
        ),
        adjustment_out_value=Sum(
            F('quantity') * F('unit_cost_snapshot'),
            filter=Q(movement_type='ADJUSTMENT_OUT', unit_cost_snapshot__isnull=False),
            output_field=DecimalField(max_digits=18, decimal_places=6),
            default=Decimal('0')
        ),
    ).order_by('product__name')

    rows = []
    for row in aggregated:
        theoretical_qty = row['theoretical_qty'] or Decimal('0')
        recorded_waste_qty = row['recorded_waste_qty'] or Decimal('0')
        adjustment_in_qty = row['adjustment_in_qty'] or Decimal('0')
        adjustment_out_qty = row['adjustment_out_qty'] or Decimal('0')

        # Unexplained = adjustments that brought stock UP minus those that brought it DOWN
        # Negative = net unexplained shortfall (system had more than physical count)
        unexplained_qty = adjustment_in_qty - adjustment_out_qty

        # Values
        theoretical_value = row['theoretical_value'] or Decimal('0')
        waste_value = row['waste_value'] or Decimal('0')
        adjustment_in_value = row['adjustment_in_value'] or Decimal('0')
        adjustment_out_value = row['adjustment_out_value'] or Decimal('0')
        unexplained_value = adjustment_in_value - adjustment_out_value

        # Variance percentage - honest status if no theoretical usage
        if theoretical_qty and theoretical_qty != Decimal('0'):
            variance_pct = (unexplained_qty / theoretical_qty) * 100
            variance_pct = _quantize_money(variance_pct)
            status = 'calculated'
        else:
            variance_pct = None
            status = 'no_theoretical_usage'

        rows.append({
            'product_name': row['product__name'],
            'unit_name': row['product__unit__name'],
            'movement_count': row['movement_count'],
            'theoretical_qty': theoretical_qty,
            'recorded_waste_qty': recorded_waste_qty,
            'unexplained_qty': unexplained_qty,
            'variance_pct': variance_pct,
            'status': status,
            'theoretical_value': _quantize_money(theoretical_value),
            'waste_value': _quantize_money(waste_value),
            'unexplained_value': _quantize_money(unexplained_value),
        })

    # Apply k-anonymity suppression based on movement_count
    rows = _suppress_small_cells(rows, 'product_name', min_count=K_ANON_MIN)

    return rows


def usage_variance_summary(date_from=None, date_to=None, product=None):
    """
    Convenience read for the future variance analytics view. Returns aggregated
    variance data plus totals.

    Args:
        date_from: Optional date filter (inclusive) on recorded_at.
        date_to: Optional date filter (inclusive) on recorded_at.
        product: Optional single Product instance filter.

    Returns:
        dict with keys:
            - 'rows': List of variance rows per product (k-anonymised)
            - 'total_theoretical_qty': Decimal - total theoretical usage quantity
            - 'total_theoretical_value': Decimal (2dp) - total theoretical usage value
            - 'total_waste_qty': Decimal - total recorded waste quantity
            - 'total_waste_value': Decimal (2dp) - total recorded waste value
            - 'total_unexplained_qty': Decimal - total unexplained variance quantity
            - 'total_unexplained_value': Decimal (2dp) - total unexplained variance value
            - 'overall_variance_pct': Decimal (2dp) or None - overall variance %
            - 'unvalued_movement_count': int - movements with null cost snapshot
            - 'k_anon_min': The k-anonymity threshold used
    """
    # Get the per-product rows
    rows = usage_variance_by(
        dimension='product',
        date_from=date_from,
        date_to=date_to,
        product=product,
    )

    # Compute totals from the rows (after suppression, so totals still reconcile)
    total_theoretical_qty = sum(r['theoretical_qty'] for r in rows)
    total_theoretical_value = sum(r['theoretical_value'] for r in rows)
    total_waste_qty = sum(r['recorded_waste_qty'] for r in rows)
    total_waste_value = sum(r['waste_value'] for r in rows)
    total_unexplained_qty = sum(r['unexplained_qty'] for r in rows)
    total_unexplained_value = sum(r['unexplained_value'] for r in rows)

    # Overall variance percentage
    if total_theoretical_qty and total_theoretical_qty != Decimal('0'):
        overall_variance_pct = (total_unexplained_qty / total_theoretical_qty) * 100
        overall_variance_pct = _quantize_money(overall_variance_pct)
    else:
        overall_variance_pct = None

    # Count movements with null cost snapshot
    relevant_types = ['SALE', 'WASTE', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT']
    base_qs = StockMovement.objects.filter(
        movement_type__in=relevant_types,
        voided_by__isnull=True,
    )
    if date_from:
        base_qs = base_qs.filter(recorded_at__date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(recorded_at__date__lte=date_to)
    if product:
        base_qs = base_qs.filter(product=product)

    unvalued_movement_count = base_qs.filter(unit_cost_snapshot__isnull=True).count()

    return {
        'rows': rows,
        'total_theoretical_qty': total_theoretical_qty,
        'total_theoretical_value': _quantize_money(total_theoretical_value),
        'total_waste_qty': total_waste_qty,
        'total_waste_value': _quantize_money(total_waste_value),
        'total_unexplained_qty': total_unexplained_qty,
        'total_unexplained_value': _quantize_money(total_unexplained_value),
        'overall_variance_pct': overall_variance_pct,
        'unvalued_movement_count': unvalued_movement_count,
        'k_anon_min': K_ANON_MIN,
    }


# ---------------------------------------------------------------------------
# Stock level queries
# ---------------------------------------------------------------------------

def products_below_reorder_level():
    """
    Return active products whose stock is at or below their reorder level.

    A reorder level of zero means the product is not tracked for reordering and is
    excluded. This prevents products simply sitting at zero (with no threshold set)
    from flooding the list. Read-only.

    Returns:
        QuerySet of Product objects annotated with 'shortfall' (reorder_level minus
        stock_quantity), ordered by shortfall descending (most urgent first). Each
        product includes select_related unit and category.
    """
    from inventory.models import Product

    return Product.objects.filter(
        is_active=True,
        reorder_level__gt=0,
        stock_quantity__lte=F('reorder_level'),
    ).select_related(
        'unit', 'category'
    ).annotate(
        shortfall=F('reorder_level') - F('stock_quantity')
    ).order_by('-shortfall', 'name')
