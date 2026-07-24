"""
Tests for Stock Take service functions (F16 Part B).

Tests cover:
- start_stock_take creates lines for active products only
- record_count sets count without changing stock
- preview_stock_take returns correct discrepancies
- apply_stock_take happy path with adjustments
- Zero discrepancy writes no movement
- Delta behaviour preserves legitimate movements
- Incomplete count blocks apply
- Double apply raises
- All-or-nothing rollback on failure
- ADJUSTMENT movements not in waste analytics
"""

from decimal import Decimal

from django.test import TestCase, TransactionTestCase

from accounts.models import CustomUser
from inventory.models import (
    Category, Product, Unit, StockMovement, PurchasePrice,
    StockTake, StockTakeLine,
)
from inventory.services import (
    start_stock_take,
    record_count,
    record_counts,
    preview_stock_take,
    apply_stock_take,
    record_stock_out,
    StockValidationError,
    InsufficientStockError,
)


class StartStockTakeTests(TransactionTestCase):
    """Tests for start_stock_take function."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)

    def test_creates_lines_for_active_products_only(self):
        """start_stock_take creates one line per ACTIVE product only."""
        active1 = Product.objects.create(
            name='Active Product 1',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        active2 = Product.objects.create(
            name='Active Product 2',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('50.0000'),
            is_active=True,
        )
        inactive = Product.objects.create(
            name='Inactive Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('25.0000'),
            is_active=False,
        )

        stock_take = start_stock_take(self.user, reference='Test Count')

        self.assertEqual(stock_take.lines.count(), 2)
        product_ids = set(stock_take.lines.values_list('product_id', flat=True))
        self.assertIn(active1.pk, product_ids)
        self.assertIn(active2.pk, product_ids)
        self.assertNotIn(inactive.pk, product_ids)

    def test_snapshots_current_stock(self):
        """Each line snapshots the product's current stock_quantity."""
        product = Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('123.4567'),
            is_active=True,
        )

        stock_take = start_stock_take(self.user)

        line = stock_take.lines.get(product=product)
        self.assertEqual(line.system_quantity_snapshot, Decimal('123.4567'))

    def test_counted_quantity_is_none(self):
        """Lines are created with counted_quantity = None."""
        Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )

        stock_take = start_stock_take(self.user)

        line = stock_take.lines.first()
        self.assertIsNone(line.counted_quantity)

    def test_applied_at_is_none(self):
        """Stock take is created with applied_at = None."""
        Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )

        stock_take = start_stock_take(self.user)

        self.assertIsNone(stock_take.applied_at)
        self.assertFalse(stock_take.is_applied)

    def test_does_not_change_stock(self):
        """Starting a stock take does NOT change any product stock."""
        product = Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        initial_stock = product.stock_quantity
        initial_movements = StockMovement.objects.count()

        start_stock_take(self.user)

        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, initial_stock)
        self.assertEqual(StockMovement.objects.count(), initial_movements)

    def test_raises_if_no_active_products(self):
        """start_stock_take raises if there are no active products."""
        # Create only inactive product
        Product.objects.create(
            name='Inactive Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=False,
        )

        with self.assertRaises(StockValidationError) as ctx:
            start_stock_take(self.user)

        self.assertIn('No active products', str(ctx.exception))


class RecordCountTests(TransactionTestCase):
    """Tests for record_count function."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)
        self.product = Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        self.stock_take = start_stock_take(self.user)
        self.line = self.stock_take.lines.first()

    def test_sets_counted_quantity(self):
        """record_count sets the counted_quantity on the line."""
        record_count(self.line, Decimal('95.0000'))

        self.line.refresh_from_db()
        self.assertEqual(self.line.counted_quantity, Decimal('95.0000'))

    def test_does_not_change_stock(self):
        """Recording a count does NOT change product stock."""
        initial_stock = self.product.stock_quantity

        record_count(self.line, Decimal('50.0000'))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_rejects_negative_count(self):
        """record_count raises if counted_quantity is negative."""
        with self.assertRaises(StockValidationError) as ctx:
            record_count(self.line, Decimal('-5.0000'))

        self.assertIn('cannot be negative', str(ctx.exception))

    def test_rejects_count_on_applied_stock_take(self):
        """record_count raises if the stock take is already applied."""
        record_count(self.line, Decimal('100.0000'))
        apply_stock_take(self.stock_take, self.user)

        # Get fresh line
        self.line.refresh_from_db()

        with self.assertRaises(StockValidationError) as ctx:
            record_count(self.line, Decimal('90.0000'))

        self.assertIn('already been applied', str(ctx.exception))


class RecordCountsTests(TransactionTestCase):
    """Tests for record_counts convenience function."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)
        self.product1 = Product.objects.create(
            name='Product 1',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        self.product2 = Product.objects.create(
            name='Product 2',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('50.0000'),
            is_active=True,
        )
        self.stock_take = start_stock_take(self.user)

    def test_records_multiple_counts(self):
        """record_counts sets counts for multiple products."""
        counts = {
            self.product1.pk: Decimal('95.0000'),
            self.product2.pk: Decimal('55.0000'),
        }

        record_counts(self.stock_take, counts)

        line1 = self.stock_take.lines.get(product=self.product1)
        line2 = self.stock_take.lines.get(product=self.product2)
        self.assertEqual(line1.counted_quantity, Decimal('95.0000'))
        self.assertEqual(line2.counted_quantity, Decimal('55.0000'))

    def test_raises_for_invalid_product_id(self):
        """record_counts raises if a product_id has no line in this stock take."""
        counts = {
            99999: Decimal('100.0000'),  # Non-existent
        }

        with self.assertRaises(StockValidationError) as ctx:
            record_counts(self.stock_take, counts)

        self.assertIn('No line found', str(ctx.exception))


class PreviewStockTakeTests(TransactionTestCase):
    """Tests for preview_stock_take function."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)
        self.product1 = Product.objects.create(
            name='Product A',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        self.product2 = Product.objects.create(
            name='Product B',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('50.0000'),
            is_active=True,
        )

    def test_returns_correct_discrepancies(self):
        """preview_stock_take calculates correct discrepancies."""
        stock_take = start_stock_take(self.user)

        # Product A: snapshot 100, counted 95 -> discrepancy -5 (ADJUSTMENT_OUT)
        line1 = stock_take.lines.get(product=self.product1)
        record_count(line1, Decimal('95.0000'))

        # Product B: snapshot 50, counted 58 -> discrepancy +8 (ADJUSTMENT_IN)
        line2 = stock_take.lines.get(product=self.product2)
        record_count(line2, Decimal('58.0000'))

        preview = preview_stock_take(stock_take)

        # Find lines by product name
        line_a = next(l for l in preview.lines if l.product_name == 'Product A')
        line_b = next(l for l in preview.lines if l.product_name == 'Product B')

        self.assertEqual(line_a.discrepancy, Decimal('-5.0000'))
        self.assertEqual(line_a.movement_type, 'ADJUSTMENT_OUT')

        self.assertEqual(line_b.discrepancy, Decimal('8.0000'))
        self.assertEqual(line_b.movement_type, 'ADJUSTMENT_IN')

    def test_flags_uncounted_lines(self):
        """preview_stock_take correctly counts uncounted lines."""
        stock_take = start_stock_take(self.user)

        # Only count one product
        line1 = stock_take.lines.get(product=self.product1)
        record_count(line1, Decimal('100.0000'))

        preview = preview_stock_take(stock_take)

        self.assertEqual(preview.total_lines, 2)
        self.assertEqual(preview.counted_lines, 1)
        self.assertEqual(preview.uncounted_lines, 1)
        self.assertFalse(preview.is_ready_to_apply)

    def test_zero_discrepancy_movement_type_none(self):
        """Zero discrepancy has movement_type None."""
        stock_take = start_stock_take(self.user)

        line = stock_take.lines.get(product=self.product1)
        record_count(line, Decimal('100.0000'))  # Same as snapshot

        preview = preview_stock_take(stock_take)

        line_preview = next(l for l in preview.lines if l.product_id == self.product1.pk)
        self.assertEqual(line_preview.discrepancy, Decimal('0.0000'))
        self.assertIsNone(line_preview.movement_type)

    def test_does_not_mutate_anything(self):
        """preview_stock_take is read-only."""
        stock_take = start_stock_take(self.user)
        line = stock_take.lines.get(product=self.product1)
        record_count(line, Decimal('95.0000'))

        initial_stock = self.product1.stock_quantity
        initial_movements = StockMovement.objects.count()

        preview_stock_take(stock_take)

        self.product1.refresh_from_db()
        self.assertEqual(self.product1.stock_quantity, initial_stock)
        self.assertEqual(StockMovement.objects.count(), initial_movements)


class ApplyStockTakeHappyPathTests(TransactionTestCase):
    """Tests for apply_stock_take happy path."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)

    def test_happy_path_adjustments(self):
        """Apply creates correct ADJUSTMENT movements and updates stock."""
        product_a = Product.objects.create(
            name='Product A',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        PurchasePrice.objects.create(
            product=product_a,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
        )

        product_b = Product.objects.create(
            name='Product B',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('50.0000'),
            is_active=True,
        )
        PurchasePrice.objects.create(
            product=product_b,
            unit_price=Decimal('3.00'),
            currency='GBP',
            created_by=self.user,
        )

        stock_take = start_stock_take(self.user, reference='Happy Path Test')

        # Product A: snapshot 100, counted 95 -> ADJUSTMENT_OUT of 5
        line_a = stock_take.lines.get(product=product_a)
        record_count(line_a, Decimal('95.0000'))

        # Product B: snapshot 50, counted 58 -> ADJUSTMENT_IN of 8
        line_b = stock_take.lines.get(product=product_b)
        record_count(line_b, Decimal('58.0000'))

        result = apply_stock_take(stock_take, self.user)

        # Check stock updates
        product_a.refresh_from_db()
        product_b.refresh_from_db()
        self.assertEqual(product_a.stock_quantity, Decimal('95.0000'))
        self.assertEqual(product_b.stock_quantity, Decimal('58.0000'))

        # Check movements created
        movement_a = StockMovement.objects.get(
            product=product_a,
            movement_type='ADJUSTMENT_OUT'
        )
        self.assertEqual(movement_a.quantity, Decimal('5.0000'))
        self.assertEqual(movement_a.reason_category, 'Stock take adjustment')
        self.assertEqual(movement_a.reference_id, f'stocktake-{stock_take.pk}')

        movement_b = StockMovement.objects.get(
            product=product_b,
            movement_type='ADJUSTMENT_IN'
        )
        self.assertEqual(movement_b.quantity, Decimal('8.0000'))
        self.assertEqual(movement_b.reason_category, 'Stock take adjustment')
        self.assertEqual(movement_b.reference_id, f'stocktake-{stock_take.pk}')

        # Check discrepancies stored on lines
        line_a.refresh_from_db()
        line_b.refresh_from_db()
        self.assertEqual(line_a.discrepancy, Decimal('-5.0000'))
        self.assertEqual(line_b.discrepancy, Decimal('8.0000'))

        # Check applied_at is set
        stock_take.refresh_from_db()
        self.assertIsNotNone(stock_take.applied_at)
        self.assertTrue(stock_take.is_applied)

        # Check result counts
        self.assertEqual(result['adjustments_out'], 1)
        self.assertEqual(result['adjustments_in'], 1)


class ZeroDiscrepancyTests(TransactionTestCase):
    """Tests for zero discrepancy behaviour."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)

    def test_zero_discrepancy_no_movement(self):
        """A line counted exactly equal to its snapshot writes NO movement."""
        product = Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )

        stock_take = start_stock_take(self.user)
        line = stock_take.lines.first()
        record_count(line, Decimal('100.0000'))  # Same as snapshot

        initial_movements = StockMovement.objects.count()

        result = apply_stock_take(stock_take, self.user)

        # No new movements
        self.assertEqual(StockMovement.objects.count(), initial_movements)

        # But discrepancy is stored
        line.refresh_from_db()
        self.assertEqual(line.discrepancy, Decimal('0.0000'))

        # Result shows zero discrepancy
        self.assertEqual(result['zero_discrepancies'], 1)
        self.assertEqual(result['adjustments_in'], 0)
        self.assertEqual(result['adjustments_out'], 0)


class DeltaBehaviourTests(TransactionTestCase):
    """Tests for delta behaviour - preserving legitimate movements."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)

    def test_delta_preserves_legitimate_movements(self):
        """
        THE DELTA TEST (critical):
        Snapshot 100, counted 95 (discrepancy -5).
        BEFORE applying, record a legitimate OUT of 10 (stock now 90).
        Apply. Assert final stock is 85 (90 - 5), NOT 95.
        """
        product = Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )

        # Start stock take - snapshot is 100
        stock_take = start_stock_take(self.user)
        line = stock_take.lines.first()

        # Record count: 95 (discrepancy will be -5)
        record_count(line, Decimal('95.0000'))

        # BEFORE applying, a legitimate OUT of 10 occurs
        record_stock_out(
            product=product,
            quantity=Decimal('10.0000'),
            reason_category='Other',
            reason_notes='Legitimate sale',
            user=self.user,
        )

        # Stock is now 90
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('90.0000'))

        # Now apply the stock take
        apply_stock_take(stock_take, self.user)

        # Final stock should be 85 (90 - 5), NOT 95
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('85.0000'))


class IncompleteCountTests(TransactionTestCase):
    """Tests for incomplete count blocking apply."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)
        Product.objects.create(
            name='Product 1',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        Product.objects.create(
            name='Product 2',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('50.0000'),
            is_active=True,
        )

    def test_incomplete_count_raises(self):
        """Applying with any uncounted line raises StockValidationError."""
        stock_take = start_stock_take(self.user)

        # Only count one of the two products
        line = stock_take.lines.first()
        record_count(line, Decimal('100.0000'))

        with self.assertRaises(StockValidationError) as ctx:
            apply_stock_take(stock_take, self.user)

        self.assertIn('1 line(s) have not been counted', str(ctx.exception))

        # applied_at should still be None
        stock_take.refresh_from_db()
        self.assertIsNone(stock_take.applied_at)

        # No movements written
        self.assertEqual(
            StockMovement.objects.filter(reference_id__startswith='stocktake-').count(),
            0
        )


class DoubleApplyTests(TransactionTestCase):
    """Tests for double apply prevention."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)
        Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )

    def test_double_apply_raises(self):
        """Applying an already-applied stock take raises."""
        stock_take = start_stock_take(self.user)
        line = stock_take.lines.first()
        record_count(line, Decimal('95.0000'))

        apply_stock_take(stock_take, self.user)

        initial_movements = StockMovement.objects.count()

        with self.assertRaises(StockValidationError) as ctx:
            apply_stock_take(stock_take, self.user)

        self.assertIn('already been applied', str(ctx.exception))

        # No extra movements
        self.assertEqual(StockMovement.objects.count(), initial_movements)


class AllOrNothingTests(TransactionTestCase):
    """Tests for all-or-nothing rollback on failure."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)

    def test_all_or_nothing_rollback(self):
        """
        Two lines, the second needing an ADJUSTMENT_OUT larger than stock.
        InsufficientStockError; applied_at stays None, NO adjustment movements,
        FIRST product's stock is UNCHANGED.
        """
        product1 = Product.objects.create(
            name='Product 1',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )
        product2 = Product.objects.create(
            name='Product 2',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('10.0000'),  # Low stock
            is_active=True,
        )

        initial_stock1 = product1.stock_quantity
        initial_stock2 = product2.stock_quantity

        stock_take = start_stock_take(self.user)

        # Product 1: counted 90 (discrepancy -10, should work)
        line1 = stock_take.lines.get(product=product1)
        record_count(line1, Decimal('90.0000'))

        # Product 2: counted 0 (discrepancy -10, but only 10 in stock!)
        # This should fail because we have exactly 10, trying to remove 10... wait
        # Actually need to make it fail - set counted to something that would go negative
        # Snapshot is 10, if we count 0, discrepancy is -10
        # But stock IS 10, so ADJUSTMENT_OUT of 10 should work
        # Let me set it up so it fails...
        # Actually the snapshot is taken at start_stock_take time.
        # Let me drain the stock AFTER the snapshot

        line2 = stock_take.lines.get(product=product2)
        record_count(line2, Decimal('0.0000'))  # Discrepancy will be -10

        # Now drain product2's stock so adjustment will fail
        record_stock_out(
            product=product2,
            quantity=Decimal('5.0000'),
            reason_category='Other',
            reason_notes='Drain stock',
            user=self.user,
        )
        # Stock is now 5, but we'll try to ADJUSTMENT_OUT 10

        initial_movements = StockMovement.objects.filter(
            reference_id__startswith='stocktake-'
        ).count()

        with self.assertRaises(InsufficientStockError):
            apply_stock_take(stock_take, self.user)

        # applied_at should still be None
        stock_take.refresh_from_db()
        self.assertIsNone(stock_take.applied_at)

        # No stocktake movements written
        self.assertEqual(
            StockMovement.objects.filter(reference_id__startswith='stocktake-').count(),
            initial_movements
        )

        # Product 1 stock unchanged (rollback)
        product1.refresh_from_db()
        self.assertEqual(product1.stock_quantity, initial_stock1)


class AdjustmentNotInWasteAnalyticsTests(TransactionTestCase):
    """Tests that ADJUSTMENT movements are not in waste analytics."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Test', is_active=True)

    def test_adjustment_movements_not_waste(self):
        """ADJUSTMENT movements are not WASTE type."""
        product = Product.objects.create(
            name='Test Product',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('100.0000'),
            is_active=True,
        )

        stock_take = start_stock_take(self.user)
        line = stock_take.lines.first()
        record_count(line, Decimal('90.0000'))  # -10 discrepancy

        apply_stock_take(stock_take, self.user)

        # The movement should be ADJUSTMENT_OUT, not WASTE
        movement = StockMovement.objects.get(
            product=product,
            reference_id__startswith='stocktake-'
        )
        self.assertEqual(movement.movement_type, 'ADJUSTMENT_OUT')
        self.assertNotEqual(movement.movement_type, 'WASTE')

        # Waste analytics query (F13) would filter by movement_type='WASTE'
        waste_movements = StockMovement.objects.filter(movement_type='WASTE')
        self.assertEqual(waste_movements.count(), 0)
