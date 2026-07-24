"""
Valued wastage analytics (read-only aggregation).
"""

from decimal import Decimal

from django.db.models import Sum, Count, F, DecimalField

from inventory.models import StockMovement
from .recording import _quantize_money


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# k-anonymity threshold: aggregation cells with fewer than this many underlying
# WASTE movement rows are suppressed and merged into an 'Other' bucket.
K_ANON_MIN = 3

# Allowed grouping dimensions for valued_waste_by. Hard block on any user grouping.
ALLOWED_DIMENSIONS = frozenset({'product', 'reason_category'})


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------

def _suppress_small_cells(rows, dimension_key, min_count=K_ANON_MIN):
    """
    Merge aggregation rows backed by fewer than min_count underlying events into a
    single 'Other (suppressed, fewer than N events)' bucket, preserving summed
    totals so the grand total reconciles.

    In a single-venue SME a cell backed by 1-2 events can be re-identified to a
    person via shift/context even though we never group by user; k>=3 breaks that
    small-cell inference. Proportionate control, not a perfect guarantee.

    Args:
        rows: List of dicts from valued_waste_by aggregation, each containing
              'event_count', 'total_qty', 'valued_total', and the dimension key.
        dimension_key: The key name for the dimension ('product_name' or
                       'reason_category').
        min_count: Minimum event count threshold (default K_ANON_MIN).

    Returns:
        List of dicts with sub-threshold rows merged into an 'Other' bucket.
    """
    passed = []
    suppressed_count = 0
    suppressed_qty = Decimal('0')
    suppressed_value = Decimal('0')

    for row in rows:
        if row['event_count'] >= min_count:
            passed.append(row)
        else:
            suppressed_count += row['event_count']
            suppressed_qty += row['total_qty'] or Decimal('0')
            suppressed_value += row['valued_total'] or Decimal('0')

    # Only add suppressed bucket if there were suppressed rows
    if suppressed_count > 0:
        passed.append({
            dimension_key: f'Suppressed (fewer than {min_count} events)',
            'event_count': suppressed_count,
            'total_qty': suppressed_qty,
            'valued_total': suppressed_value,
        })

    return passed


# ---------------------------------------------------------------------------
# Analytics functions
# ---------------------------------------------------------------------------

def valued_waste_by(dimension, date_from=None, date_to=None, category=None,
                    product=None):
    """
    Aggregate WASTE stock movements into valued waste rows, grouped by one
    dimension. Read-only. Never groups or filters by user — per-person waste
    analytics is prohibited (GDPR Arts 22/35); this function has no user parameter
    by construction.

    Valued waste per row = quantity * unit_cost_snapshot. Rows with NULL
    unit_cost_snapshot are EXCLUDED from the valued sum (they are reported
    separately as unvalued waste via valued_waste_summary).

    k-anonymity: any group built from fewer than K_ANON_MIN (3) underlying WASTE
    rows is suppressed and merged into a 'Suppressed (fewer than 3 events)'
    bucket so totals still reconcile. In a single-venue SME a 1-2 event cell can be
    re-identified to a person by shift/context even without grouping by user; k>=3
    breaks that small-cell inference. Proportionate control, not a guarantee.

    Args:
        dimension: One of 'product' or 'reason_category' (the grouping key).
                   Anything else raises ValueError — in particular 'recorded_by'
                   is impossible by design.
        date_from: Optional date filter (inclusive) on recorded_at.
        date_to: Optional date filter (inclusive) on recorded_at.
        category: Optional single reason_category filter.
        product: Optional single Product instance filter.

    Returns:
        List of dicts, each containing:
            - The dimension key (either 'product_name' or 'reason_category')
            - 'event_count': Number of WASTE movements in this group
            - 'total_qty': Sum of quantities (Decimal)
            - 'valued_total': Sum of quantity * unit_cost_snapshot (Decimal, 2dp)

    Raises:
        ValueError: If dimension is not in ALLOWED_DIMENSIONS.
    """
    # Hard block on any dimension not explicitly allowed
    if dimension not in ALLOWED_DIMENSIONS:
        raise ValueError(
            f"Invalid dimension '{dimension}'. "
            f"Allowed dimensions: {sorted(ALLOWED_DIMENSIONS)}. "
            "Per-person grouping is prohibited."
        )

    # Base queryset: live WASTE movements only — excludes VOID rows by type, and
    # excludes any WASTE that has since been voided or corrected (voided_by set).
    base_qs = StockMovement.objects.filter(
        movement_type='WASTE',
        voided_by__isnull=True,
    )

    # Apply optional filters (all non-personal)
    if date_from:
        base_qs = base_qs.filter(recorded_at__date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(recorded_at__date__lte=date_to)
    if category:
        base_qs = base_qs.filter(reason_category=category)
    if product:
        base_qs = base_qs.filter(product=product)

    # Only include rows with a price snapshot (valued waste)
    valued_qs = base_qs.filter(unit_cost_snapshot__isnull=False)

    # Determine grouping and output key
    if dimension == 'product':
        group_fields = ['product__id', 'product__name']
        dimension_key = 'product_name'
    else:  # reason_category
        group_fields = ['reason_category']
        dimension_key = 'reason_category'

    # Aggregate with high precision, quantize at the boundary
    aggregated = valued_qs.values(*group_fields).annotate(
        event_count=Count('id'),
        total_qty=Sum('quantity'),
        valued_total=Sum(
            F('quantity') * F('unit_cost_snapshot'),
            output_field=DecimalField(max_digits=18, decimal_places=6)
        ),
    ).order_by('-valued_total')

    # Transform to consistent output format
    rows = []
    for row in aggregated:
        if dimension == 'product':
            dim_value = row['product__name']
        else:
            dim_value = row['reason_category'] or 'Unknown'

        rows.append({
            dimension_key: dim_value,
            'event_count': row['event_count'],
            'total_qty': row['total_qty'] or Decimal('0'),
            'valued_total': _quantize_money(row['valued_total'] or Decimal('0')),
        })

    # Apply k-anonymity suppression
    rows = _suppress_small_cells(rows, dimension_key, min_count=K_ANON_MIN)

    return rows


def valued_waste_summary(date_from=None, date_to=None, category=None, product=None):
    """
    Convenience read for the valued wastage analytics view. Returns aggregated
    waste data grouped by product and by reason category, plus totals.

    Rows with NULL unit_cost_snapshot are reported separately as unvalued waste
    (quantity + event count) — never folded into £0 — so data gaps are visible
    and loss is never understated.

    Args:
        date_from: Optional date filter (inclusive) on recorded_at.
        date_to: Optional date filter (inclusive) on recorded_at.
        category: Optional single reason_category filter.
        product: Optional single Product instance filter.

    Returns:
        dict with keys:
            - 'by_product': List of aggregated rows by product (k-anonymised)
            - 'by_category': List of aggregated rows by reason_category (k-anonymised)
            - 'valued_total': Decimal (2dp) — sum of all valued waste £
            - 'valued_event_count': int — count of valued waste movements
            - 'valued_total_qty': Decimal — total quantity with price snapshots
            - 'unvalued_event_count': int — rows with no price snapshot
            - 'unvalued_total_qty': Decimal — quantity that could NOT be valued
            - 'k_anon_min': The k-anonymity threshold used
    """
    # Build base queryset: live WASTE only (excludes voided/corrected)
    base_qs = StockMovement.objects.filter(
        movement_type='WASTE',
        voided_by__isnull=True,
    )

    if date_from:
        base_qs = base_qs.filter(recorded_at__date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(recorded_at__date__lte=date_to)
    if category:
        base_qs = base_qs.filter(reason_category=category)
    if product:
        base_qs = base_qs.filter(product=product)

    # Split valued vs unvalued
    valued_qs = base_qs.filter(unit_cost_snapshot__isnull=False)
    unvalued_qs = base_qs.filter(unit_cost_snapshot__isnull=True)

    # Aggregate valued totals (high precision, quantize at boundary)
    valued_agg = valued_qs.aggregate(
        event_count=Count('id'),
        total_qty=Sum('quantity'),
        total_value=Sum(
            F('quantity') * F('unit_cost_snapshot'),
            output_field=DecimalField(max_digits=18, decimal_places=6)
        ),
    )

    # Aggregate unvalued totals
    unvalued_agg = unvalued_qs.aggregate(
        event_count=Count('id'),
        total_qty=Sum('quantity'),
    )

    # Get breakdowns by dimension (filters passed through)
    by_product = valued_waste_by(
        'product', date_from=date_from, date_to=date_to,
        category=category, product=product
    )
    by_category = valued_waste_by(
        'reason_category', date_from=date_from, date_to=date_to,
        category=category, product=product
    )

    return {
        'by_product': by_product,
        'by_category': by_category,
        'valued_total': _quantize_money(valued_agg['total_value'] or Decimal('0')),
        'valued_event_count': valued_agg['event_count'] or 0,
        'valued_total_qty': valued_agg['total_qty'] or Decimal('0'),
        'unvalued_event_count': unvalued_agg['event_count'] or 0,
        'unvalued_total_qty': unvalued_agg['total_qty'] or Decimal('0'),
        'k_anon_min': K_ANON_MIN,
    }
