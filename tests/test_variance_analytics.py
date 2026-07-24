"""
Tests for usage variance analytics (F15e Stage 2).

Tests cover:
- Hand-checkable variance calculation: SALE, WASTE, ADJUSTMENT movements
- Surplus scenario (ADJUSTMENT_IN gives positive unexplained)
- No theoretical usage: variance_pct None with status, never 0% or division error
- Voided movements excluded (for voidable types: IN, OUT, WASTE)
- Date filtering
- Null cost snapshot handling (excluded from money, reported as unvalued)
- Orion: dimension='recorded_by' raises ValueError
- k-anonymity suppression with totals reconciliation
"""

from decimal import Decimal
from datetime import date, timedelta

from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model

from inventory.models import (
    Product, Category, Unit, StockMovement, PurchasePrice,
    StockTake, StockTakeLine,
)
from inventory.services import (
    usage_variance_by,
    usage_variance_summary,
    K_ANON_MIN,
    ALLOWED_VARIANCE_DIMENSIONS,
    record_stock_in,
    void_movement,
)
from inventory.services.stock_take import (
    start_stock_take,
    record_count,
    apply_stock_take,
)
from waste.services import record_waste

CustomUser = get_user_model()


class HandCheckableVarianceTests(TransactionTestCase):
    """Hand-checkable variance calculation tests."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('200.0000'),
        )
        # Set price: 2.50 per kg
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
        )
        self.staff = CustomUser.objects.create_user(
            username='staff',
            password='testpass',
            role=CustomUser.Role.STAFF,
        )
        self.manager = CustomUser.objects.create_user(
            username='manager',
            password='testpass',
            role=CustomUser.Role.MANAGER,
        )

    def test_hand_checkable_variance(self):
        """
        One product with SALE movements totalling 100 units, a WASTE of 5,
        and a stock-take ADJUSTMENT_OUT of 3.

        Expected:
            theoretical_qty = 100
            recorded_waste_qty = 5
            unexplained_qty = -3 (net shortfall)
            variance_pct = -3.0%

        Money figures (at 2.50/unit):
            theoretical_value = 100 * 2.50 = 250.00
            waste_value = 5 * 2.50 = 12.50
            unexplained_value = -3 * 2.50 = -7.50
        """
        # Create SALE movements totalling 100 units (enough for k-anon)
        for _ in range(4):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('25.0000'),
                unit_cost_snapshot=Decimal('2.50'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Create WASTE of 5 units
        record_waste(
            product=self.product,
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.staff,
        )

        # Create stock-take with ADJUSTMENT_OUT of 3 (shortfall)
        # start_stock_take creates lines for all active products
        stock_take = start_stock_take(user=self.manager, reference='test-take')

        # Find the line for our product
        line = stock_take.lines.get(product=self.product)

        # System shows 200 - 5 (waste) = 195
        # For adjustment_out of 3, counted should be system - 3 = 192
        self.product.refresh_from_db()
        system_qty = line.system_quantity_snapshot
        record_count(line, system_qty - Decimal('3.0000'))
        apply_stock_take(stock_take, self.manager)

        # Get variance
        rows = usage_variance_by('product')

        # Find our product
        tomatoes = next(r for r in rows if r['product_name'] == 'Tomatoes')

        # Check quantities
        self.assertEqual(tomatoes['theoretical_qty'], Decimal('100.0000'))
        self.assertEqual(tomatoes['recorded_waste_qty'], Decimal('5.0000'))
        self.assertEqual(tomatoes['unexplained_qty'], Decimal('-3.0000'))

        # Check variance percentage
        self.assertEqual(tomatoes['variance_pct'], Decimal('-3.00'))
        self.assertEqual(tomatoes['status'], 'calculated')

        # Check money figures (hand-calculated)
        self.assertEqual(tomatoes['theoretical_value'], Decimal('250.00'))
        self.assertEqual(tomatoes['waste_value'], Decimal('12.50'))
        self.assertEqual(tomatoes['unexplained_value'], Decimal('-7.50'))

    def test_surplus_adjustment_in_gives_positive_unexplained(self):
        """ADJUSTMENT_IN gives a positive unexplained figure (surplus found)."""
        # Create SALE movements (for k-anon and theoretical usage)
        for _ in range(3):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('10.0000'),
                unit_cost_snapshot=Decimal('2.50'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Stock take that finds surplus (counted > system)
        stock_take = start_stock_take(user=self.manager)
        line = stock_take.lines.get(product=self.product)
        system_qty = line.system_quantity_snapshot
        record_count(line, system_qty + Decimal('5.0000'))
        apply_stock_take(stock_take, self.manager)

        rows = usage_variance_by('product')
        tomatoes = next(r for r in rows if r['product_name'] == 'Tomatoes')

        # Positive unexplained = surplus
        self.assertEqual(tomatoes['unexplained_qty'], Decimal('5.0000'))
        self.assertGreater(tomatoes['variance_pct'], Decimal('0'))

    def test_no_theoretical_usage_status(self):
        """
        Adjustments but no SALE movements in the period -> variance_pct None
        with explicit status 'no_theoretical_usage', never 0% and never a
        division error.
        """
        # Create product2 with only adjustment movements
        product2 = Product.objects.create(
            name='Onions',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('50.0000'),
        )
        PurchasePrice.objects.create(
            product=product2,
            unit_price=Decimal('1.00'),
            currency='GBP',
        )

        # Stock take with shortfall (creates ADJUSTMENT_OUT)
        stock_take = start_stock_take(user=self.manager)
        line = stock_take.lines.get(product=product2)
        record_count(line, Decimal('45.0000'))  # 5 short
        # Count the other products too (required for apply)
        for other_line in stock_take.lines.exclude(product=product2):
            record_count(other_line, other_line.system_quantity_snapshot)
        apply_stock_take(stock_take, self.manager)

        # Add more adjustments to meet k-anon threshold
        StockMovement.objects.create(
            product=product2,
            quantity=Decimal('2.0000'),
            unit_cost_snapshot=Decimal('1.00'),
            movement_type='ADJUSTMENT_OUT',
            recorded_by=self.manager,
        )
        StockMovement.objects.create(
            product=product2,
            quantity=Decimal('1.0000'),
            unit_cost_snapshot=Decimal('1.00'),
            movement_type='ADJUSTMENT_OUT',
            recorded_by=self.manager,
        )

        rows = usage_variance_by('product')
        onions = next((r for r in rows if r['product_name'] == 'Onions'), None)

        # Should exist and have honest status
        self.assertIsNotNone(onions)
        self.assertEqual(onions['theoretical_qty'], Decimal('0'))
        self.assertIsNone(onions['variance_pct'])
        self.assertEqual(onions['status'], 'no_theoretical_usage')


class VoidedExcludedTests(TransactionTestCase):
    """
    Tests that voided movements are excluded.

    Note: Only IN, OUT, WASTE movements can be voided. SALE and ADJUSTMENT
    types cannot be voided directly, so we test with WASTE movements.
    """

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
        )
        self.staff = CustomUser.objects.create_user(
            username='staff',
            password='testpass',
            role=CustomUser.Role.STAFF,
        )
        self.manager = CustomUser.objects.create_user(
            username='manager',
            password='testpass',
            role=CustomUser.Role.MANAGER,
        )

    def test_voided_waste_excluded(self):
        """A voided WASTE movement does not count in recorded_waste_qty."""
        # Create SALE movements for theoretical usage (for k-anon)
        for _ in range(3):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('10.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Create 3 WASTE movements
        wastes = []
        for _ in range(3):
            w = record_waste(
                product=self.product,
                quantity=Decimal('5.0000'),
                unit=self.kg_unit,
                waste_category='Product expired',
                user=self.staff,
            )
            wastes.append(w)

        # Before void: 15 waste qty
        rows_before = usage_variance_by('product')
        tomatoes_before = next(r for r in rows_before if r['product_name'] == 'Tomatoes')
        self.assertEqual(tomatoes_before['recorded_waste_qty'], Decimal('15.0000'))

        # Void one waste
        void_movement(wastes[0].stock_movement, 'Test void', self.manager)

        # After void: 10 waste qty (voided excluded)
        rows_after = usage_variance_by('product')
        tomatoes_after = next(r for r in rows_after if r['product_name'] == 'Tomatoes')
        self.assertEqual(tomatoes_after['recorded_waste_qty'], Decimal('10.0000'))

    def test_voided_by_field_excludes_movements(self):
        """
        Movements with voided_by set are excluded from variance.
        We simulate this by directly setting voided_by on a movement.
        """
        # Create SALE movements for theoretical usage
        movements = []
        for _ in range(4):
            m = StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('10.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )
            movements.append(m)

        # Before: 40 theoretical qty
        rows_before = usage_variance_by('product')
        tomatoes_before = next(r for r in rows_before if r['product_name'] == 'Tomatoes')
        self.assertEqual(tomatoes_before['theoretical_qty'], Decimal('40.0000'))

        # Create a VOID that points to one SALE (simulating it being voided)
        void_rec = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            unit_cost_snapshot=Decimal('2.00'),
            movement_type='VOID',
            recorded_by=self.manager,
            voids=movements[0],
        )

        # After: 30 theoretical qty (one SALE now has voided_by set)
        rows_after = usage_variance_by('product')
        tomatoes_after = next(r for r in rows_after if r['product_name'] == 'Tomatoes')
        self.assertEqual(tomatoes_after['theoretical_qty'], Decimal('30.0000'))


class DateFilteringTests(TransactionTestCase):
    """Tests for date range filtering."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
        )
        self.staff = CustomUser.objects.create_user(
            username='staff',
            password='testpass',
            role=CustomUser.Role.STAFF,
        )

    def test_movements_outside_date_range_excluded(self):
        """Movements outside the date range are excluded."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        last_week = today - timedelta(days=7)

        # Create movements - we'll manually set recorded_at
        # Movement from last week (outside range)
        m1 = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            unit_cost_snapshot=Decimal('2.00'),
            movement_type='SALE',
            recorded_by=self.staff,
        )
        StockMovement.objects.filter(pk=m1.pk).update(recorded_at=last_week)

        # Movements from yesterday and today (inside range)
        for _ in range(3):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Filter to yesterday-today
        rows = usage_variance_by('product', date_from=yesterday, date_to=today)
        tomatoes = next(r for r in rows if r['product_name'] == 'Tomatoes')

        # Should be 15 (3 movements of 5), not 25
        self.assertEqual(tomatoes['theoretical_qty'], Decimal('15.0000'))


class NullCostSnapshotTests(TransactionTestCase):
    """Tests for movements with null cost snapshots."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        # Product WITHOUT a price
        self.product_no_price = Product.objects.create(
            name='Unpriced',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        # Product WITH a price
        self.product_with_price = Product.objects.create(
            name='Priced',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=self.product_with_price,
            unit_price=Decimal('3.00'),
            currency='GBP',
        )
        self.staff = CustomUser.objects.create_user(
            username='staff',
            password='testpass',
            role=CustomUser.Role.STAFF,
        )

    def test_null_snapshot_excluded_from_money_qty_counted(self):
        """
        Movements with null cost snapshot are excluded from money totals
        but quantity is still counted.
        """
        # Create movements with null snapshot
        for _ in range(4):
            StockMovement.objects.create(
                product=self.product_no_price,
                quantity=Decimal('10.0000'),
                unit_cost_snapshot=None,  # No price
                movement_type='SALE',
                recorded_by=self.staff,
            )

        rows = usage_variance_by('product')
        unpriced = next(r for r in rows if r['product_name'] == 'Unpriced')

        # Quantity counted
        self.assertEqual(unpriced['theoretical_qty'], Decimal('40.0000'))
        # Money is zero (excluded)
        self.assertEqual(unpriced['theoretical_value'], Decimal('0.00'))

    def test_unvalued_movement_count_in_summary(self):
        """Summary reports count of movements with null cost snapshot."""
        # Create movements with null snapshot
        for _ in range(3):
            StockMovement.objects.create(
                product=self.product_no_price,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=None,
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Create valued movements
        for _ in range(3):
            StockMovement.objects.create(
                product=self.product_with_price,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=Decimal('3.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        summary = usage_variance_summary()
        self.assertEqual(summary['unvalued_movement_count'], 3)


class OrionDimensionTests(TestCase):
    """Tests for dimension restrictions (Orion)."""

    def test_recorded_by_dimension_raises_value_error(self):
        """usage_variance_by(dimension='recorded_by') raises ValueError."""
        with self.assertRaises(ValueError) as context:
            usage_variance_by(dimension='recorded_by')

        self.assertIn('recorded_by', str(context.exception).lower())
        self.assertIn('prohibited', str(context.exception).lower())

    def test_user_dimension_raises_value_error(self):
        """Any user-related dimension raises ValueError."""
        with self.assertRaises(ValueError):
            usage_variance_by(dimension='user')

    def test_allowed_dimensions_constant(self):
        """ALLOWED_VARIANCE_DIMENSIONS contains only 'product'."""
        self.assertEqual(ALLOWED_VARIANCE_DIMENSIONS, frozenset({'product'}))


class KAnonymityTests(TransactionTestCase):
    """Tests for k-anonymity suppression."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.staff = CustomUser.objects.create_user(
            username='staff',
            password='testpass',
            role=CustomUser.Role.STAFF,
        )

    def test_product_with_few_movements_suppressed(self):
        """A product backed by fewer than K_ANON_MIN movements is suppressed."""
        # Product with only 2 movements (below K_ANON_MIN=3)
        product_few = Product.objects.create(
            name='FewMoves',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=product_few,
            unit_price=Decimal('1.00'),
            currency='GBP',
        )
        for _ in range(2):
            StockMovement.objects.create(
                product=product_few,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=Decimal('1.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Product with 5 movements (above threshold)
        product_many = Product.objects.create(
            name='ManyMoves',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=product_many,
            unit_price=Decimal('2.00'),
            currency='GBP',
        )
        for _ in range(5):
            StockMovement.objects.create(
                product=product_many,
                quantity=Decimal('10.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        rows = usage_variance_by('product')
        product_names = [r['product_name'] for r in rows]

        # FewMoves suppressed
        self.assertNotIn('FewMoves', product_names)
        # ManyMoves passes
        self.assertIn('ManyMoves', product_names)
        # Suppressed bucket exists
        suppressed = [r for r in rows if 'suppressed' in r['product_name'].lower()]
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0]['movement_count'], 2)

    def test_totals_reconcile_after_suppression(self):
        """Suppressed rows merge into bucket so totals reconcile."""
        # Product with 2 movements: 10 qty, 10.00 value
        product_few = Product.objects.create(
            name='FewMoves',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=product_few,
            unit_price=Decimal('1.00'),
            currency='GBP',
        )
        for _ in range(2):
            StockMovement.objects.create(
                product=product_few,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=Decimal('1.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        # Product with 4 movements: 20 qty, 40.00 value
        product_many = Product.objects.create(
            name='ManyMoves',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=product_many,
            unit_price=Decimal('2.00'),
            currency='GBP',
        )
        for _ in range(4):
            StockMovement.objects.create(
                product=product_many,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        summary = usage_variance_summary()

        # Expected totals: 10 + 20 = 30 qty, 10 + 40 = 50 value
        self.assertEqual(summary['total_theoretical_qty'], Decimal('30.0000'))
        self.assertEqual(summary['total_theoretical_value'], Decimal('50.00'))


class VarianceSummaryTests(TransactionTestCase):
    """Tests for usage_variance_summary convenience function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
        )
        self.staff = CustomUser.objects.create_user(
            username='staff',
            password='testpass',
            role=CustomUser.Role.STAFF,
        )
        self.manager = CustomUser.objects.create_user(
            username='manager',
            password='testpass',
            role=CustomUser.Role.MANAGER,
        )

    def test_summary_contains_all_fields(self):
        """Summary contains all expected fields."""
        # Create enough movements
        for _ in range(4):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('10.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='SALE',
                recorded_by=self.staff,
            )

        summary = usage_variance_summary()

        self.assertIn('rows', summary)
        self.assertIn('total_theoretical_qty', summary)
        self.assertIn('total_theoretical_value', summary)
        self.assertIn('total_waste_qty', summary)
        self.assertIn('total_waste_value', summary)
        self.assertIn('total_unexplained_qty', summary)
        self.assertIn('total_unexplained_value', summary)
        self.assertIn('overall_variance_pct', summary)
        self.assertIn('unvalued_movement_count', summary)
        self.assertIn('k_anon_min', summary)

    def test_overall_variance_pct_none_when_no_theoretical(self):
        """Overall variance_pct is None when total theoretical is zero."""
        # Only adjustments, no sales
        for _ in range(3):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('5.0000'),
                unit_cost_snapshot=Decimal('2.00'),
                movement_type='ADJUSTMENT_OUT',
                recorded_by=self.manager,
            )

        summary = usage_variance_summary()
        self.assertIsNone(summary['overall_variance_pct'])
