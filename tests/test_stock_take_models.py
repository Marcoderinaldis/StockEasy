"""
Tests for Stock Take models and adjustment functionality (F16 Part A).

Tests cover:
- StockTake model creation and properties
- StockTakeLine model with FK relationships
- Unique constraint on (stock_take, product)
- 'Stock take adjustment' category validity
- record_movement with ADJUSTMENT_IN/ADJUSTMENT_OUT
- record_adjustment_in/out end to end
- ADJUSTMENT movements are NOT voidable
- Auditlog integration for StockTake
"""

from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase

from auditlog.models import LogEntry

from accounts.models import CustomUser
from inventory.models import (
    Category, Product, Unit, StockMovement, PurchasePrice,
    StockTake, StockTakeLine,
)
from inventory.services import (
    record_movement,
    record_adjustment_in,
    record_adjustment_out,
    void_movement,
    StockValidationError,
    InsufficientStockError,
)
from waste.models import WasteRecord


class StockTakeModelTests(TestCase):
    """Tests for StockTake model."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )

    def test_stock_take_creation(self):
        """StockTake can be created with basic fields."""
        stock_take = StockTake.objects.create(
            reference='Count 2026-07',
            notes='Monthly count',
            counted_by=self.user,
        )

        self.assertIsNotNone(stock_take.pk)
        self.assertEqual(stock_take.reference, 'Count 2026-07')
        self.assertEqual(stock_take.notes, 'Monthly count')
        self.assertEqual(stock_take.counted_by, self.user)
        self.assertIsNotNone(stock_take.started_at)

    def test_applied_at_defaults_to_none(self):
        """applied_at is None by default (draft state)."""
        stock_take = StockTake.objects.create(
            counted_by=self.user,
        )

        self.assertIsNone(stock_take.applied_at)

    def test_is_applied_false_when_not_applied(self):
        """is_applied property returns False when applied_at is None."""
        stock_take = StockTake.objects.create(
            counted_by=self.user,
        )

        self.assertFalse(stock_take.is_applied)

    def test_is_applied_true_when_applied(self):
        """is_applied property returns True when applied_at is set."""
        from django.utils import timezone

        stock_take = StockTake.objects.create(
            counted_by=self.user,
            applied_at=timezone.now(),
        )

        self.assertTrue(stock_take.is_applied)

    def test_str_representation(self):
        """__str__ shows ID and reference."""
        stock_take = StockTake.objects.create(
            reference='Test Ref',
            counted_by=self.user,
        )

        self.assertEqual(str(stock_take), f"Stock take #{stock_take.pk} (Test Ref)")

    def test_str_representation_no_ref(self):
        """__str__ shows 'no ref' when reference is None."""
        stock_take = StockTake.objects.create(
            counted_by=self.user,
        )

        self.assertEqual(str(stock_take), f"Stock take #{stock_take.pk} (no ref)")


class StockTakeLineModelTests(TestCase):
    """Tests for StockTakeLine model."""

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
        self.stock_take = StockTake.objects.create(
            reference='Test Count',
            counted_by=self.user,
        )

    def test_line_creation(self):
        """StockTakeLine can be created with required fields."""
        line = StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
            counted_quantity=Decimal('95.0000'),
        )

        self.assertIsNotNone(line.pk)
        self.assertEqual(line.stock_take, self.stock_take)
        self.assertEqual(line.product, self.product)
        self.assertEqual(line.system_quantity_snapshot, Decimal('100.0000'))
        self.assertEqual(line.counted_quantity, Decimal('95.0000'))

    def test_stock_take_lines_related_name(self):
        """stock_take.lines returns related lines."""
        line1 = StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
        )

        product2 = Product.objects.create(
            name='Product 2',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('50.0000'),
            is_active=True,
        )
        line2 = StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=product2,
            system_quantity_snapshot=Decimal('50.0000'),
        )

        lines = list(self.stock_take.lines.all())
        self.assertEqual(len(lines), 2)
        self.assertIn(line1, lines)
        self.assertIn(line2, lines)

    def test_cascade_delete_from_stock_take(self):
        """Deleting StockTake cascades to lines."""
        StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
        )

        stock_take_pk = self.stock_take.pk
        self.stock_take.delete()

        self.assertEqual(StockTakeLine.objects.filter(stock_take_id=stock_take_pk).count(), 0)

    def test_protect_on_product_delete(self):
        """Deleting Product with lines raises ProtectedError."""
        StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
        )

        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.product.delete()


class StockTakeLineUniqueConstraintTests(TransactionTestCase):
    """Tests for unique constraint on (stock_take, product)."""

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
        self.stock_take = StockTake.objects.create(
            reference='Test Count',
            counted_by=self.user,
        )

    def test_unique_product_per_stock_take(self):
        """Cannot create two lines for the same product in one stock take."""
        StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
        )

        with self.assertRaises(IntegrityError):
            StockTakeLine.objects.create(
                stock_take=self.stock_take,
                product=self.product,
                system_quantity_snapshot=Decimal('100.0000'),
            )

    def test_same_product_different_stock_takes_allowed(self):
        """Same product can appear in different stock takes."""
        stock_take2 = StockTake.objects.create(
            reference='Test Count 2',
            counted_by=self.user,
        )

        line1 = StockTakeLine.objects.create(
            stock_take=self.stock_take,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
        )
        line2 = StockTakeLine.objects.create(
            stock_take=stock_take2,
            product=self.product,
            system_quantity_snapshot=Decimal('100.0000'),
        )

        self.assertIsNotNone(line1.pk)
        self.assertIsNotNone(line2.pk)


class StockTakeAdjustmentCategoryTests(TestCase):
    """Tests for 'Stock take adjustment' category."""

    def test_category_valid_on_stock_movement(self):
        """'Stock take adjustment' is a valid choice for StockMovement."""
        choices = dict(StockMovement.REASON_CATEGORY_CHOICES)
        self.assertIn('Stock take adjustment', choices)

    def test_category_valid_on_waste_record(self):
        """'Stock take adjustment' is a valid choice for WasteRecord."""
        choices = dict(WasteRecord.WASTE_CATEGORY_CHOICES)
        self.assertIn('Stock take adjustment', choices)


class RecordMovementAdjustmentTests(TransactionTestCase):
    """Tests for record_movement with ADJUSTMENT types."""

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

    def test_adjustment_in_increments_stock(self):
        """ADJUSTMENT_IN increases product stock."""
        initial_stock = self.product.stock_quantity

        movement = record_movement(
            product=self.product,
            movement_type='ADJUSTMENT_IN',
            quantity=Decimal('10'),
            unit=self.gram,
            reason_category='Stock take adjustment',
            user=self.user,
        )

        self.product.refresh_from_db()
        self.assertEqual(movement.movement_type, 'ADJUSTMENT_IN')
        self.assertEqual(self.product.stock_quantity, initial_stock + Decimal('10'))

    def test_adjustment_out_decrements_stock(self):
        """ADJUSTMENT_OUT decreases product stock."""
        initial_stock = self.product.stock_quantity

        movement = record_movement(
            product=self.product,
            movement_type='ADJUSTMENT_OUT',
            quantity=Decimal('10'),
            unit=self.gram,
            reason_category='Stock take adjustment',
            user=self.user,
        )

        self.product.refresh_from_db()
        self.assertEqual(movement.movement_type, 'ADJUSTMENT_OUT')
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('10'))

    def test_adjustment_out_blocks_negative_stock(self):
        """ADJUSTMENT_OUT raises InsufficientStockError if it would go negative."""
        with self.assertRaises(InsufficientStockError):
            record_movement(
                product=self.product,
                movement_type='ADJUSTMENT_OUT',
                quantity=Decimal('200'),  # More than available 100
                unit=self.gram,
                reason_category='Stock take adjustment',
                user=self.user,
            )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('100.0000'))


class RecordAdjustmentFunctionsTests(TransactionTestCase):
    """Tests for record_adjustment_in and record_adjustment_out functions."""

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
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
        )

    def test_record_adjustment_in_end_to_end(self):
        """record_adjustment_in creates correct movement and updates stock."""
        initial_stock = self.product.stock_quantity

        movement = record_adjustment_in(
            product=self.product,
            quantity=Decimal('15'),
            reason_category='Stock take adjustment',
            reason_notes='Found extra stock',
            user=self.user,
            reference_id='stocktake-123',
        )

        self.product.refresh_from_db()

        # Check movement
        self.assertEqual(movement.movement_type, 'ADJUSTMENT_IN')
        self.assertEqual(movement.quantity, Decimal('15.0000'))
        self.assertEqual(movement.reason_category, 'Stock take adjustment')
        self.assertEqual(movement.reason_notes, 'Found extra stock')
        self.assertEqual(movement.reference_id, 'stocktake-123')
        self.assertEqual(movement.unit_cost_snapshot, Decimal('2.50'))

        # Check stock
        self.assertEqual(self.product.stock_quantity, initial_stock + Decimal('15'))

    def test_record_adjustment_out_end_to_end(self):
        """record_adjustment_out creates correct movement and updates stock."""
        initial_stock = self.product.stock_quantity

        movement = record_adjustment_out(
            product=self.product,
            quantity=Decimal('10'),
            reason_category='Stock take adjustment',
            reason_notes='Shrinkage found',
            user=self.user,
            reference_id='stocktake-456',
        )

        self.product.refresh_from_db()

        # Check movement
        self.assertEqual(movement.movement_type, 'ADJUSTMENT_OUT')
        self.assertEqual(movement.quantity, Decimal('10.0000'))
        self.assertEqual(movement.reason_category, 'Stock take adjustment')
        self.assertEqual(movement.reason_notes, 'Shrinkage found')
        self.assertEqual(movement.reference_id, 'stocktake-456')
        self.assertEqual(movement.unit_cost_snapshot, Decimal('2.50'))

        # Check stock
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('10'))

    def test_record_adjustment_out_insufficient_stock(self):
        """record_adjustment_out raises InsufficientStockError when stock is short."""
        with self.assertRaises(InsufficientStockError):
            record_adjustment_out(
                product=self.product,
                quantity=Decimal('150'),
                reason_category='Stock take adjustment',
                reason_notes='Too much',
                user=self.user,
            )


class AdjustmentNotVoidableTests(TransactionTestCase):
    """Tests confirming ADJUSTMENT movements are NOT voidable."""

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

    def test_adjustment_in_not_voidable(self):
        """void_movement raises for ADJUSTMENT_IN movement."""
        movement = record_adjustment_in(
            product=self.product,
            quantity=Decimal('10'),
            reason_category='Stock take adjustment',
            reason_notes='Test',
            user=self.user,
        )

        with self.assertRaises(StockValidationError) as ctx:
            void_movement(movement, 'Trying to void', self.user)

        self.assertIn('cannot be voided', str(ctx.exception))

    def test_adjustment_out_not_voidable(self):
        """void_movement raises for ADJUSTMENT_OUT movement."""
        movement = record_adjustment_out(
            product=self.product,
            quantity=Decimal('10'),
            reason_category='Stock take adjustment',
            reason_notes='Test',
            user=self.user,
        )

        with self.assertRaises(StockValidationError) as ctx:
            void_movement(movement, 'Trying to void', self.user)

        self.assertIn('cannot be voided', str(ctx.exception))


class StockTakeAuditlogTests(TransactionTestCase):
    """Tests for auditlog integration with StockTake."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )

    def test_stock_take_creation_logged(self):
        """Creating a StockTake writes an auditlog LogEntry."""
        initial_count = LogEntry.objects.count()

        stock_take = StockTake.objects.create(
            reference='Audit Test',
            counted_by=self.user,
        )

        # Should have at least one new log entry for StockTake
        new_entries = LogEntry.objects.filter(
            object_pk=str(stock_take.pk),
            content_type__model='stocktake',
        )
        self.assertGreaterEqual(new_entries.count(), 1)

        # Check the action is CREATE
        create_entry = new_entries.filter(action=LogEntry.Action.CREATE).first()
        self.assertIsNotNone(create_entry)
