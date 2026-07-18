"""
Tests for Order and OrderLine models (F15a).

Tests cover:
- Order and OrderLine model creation
- SALE movement type exists in StockMovement choices
- Auditlog registration for Order and OrderLine
- OrderLine.quantity MinValueValidator(1) enforcement
- Snapshot field preservation
"""

from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from auditlog.models import LogEntry

from inventory.models import (
    Product, Category, Unit, StockMovement, Order, OrderLine,
)
from recipes.models import Recipe

CustomUser = get_user_model()


class OrderModelTests(TransactionTestCase):
    """Tests for Order model."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='testuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

    def test_order_creation_with_reference(self):
        """Order can be created with a reference."""
        order = Order.objects.create(
            reference='Table 5',
            notes='No onions',
            placed_by=self.user,
        )
        self.assertEqual(order.reference, 'Table 5')
        self.assertEqual(order.notes, 'No onions')
        self.assertEqual(order.placed_by, self.user)
        self.assertIsNotNone(order.placed_at)

    def test_order_creation_without_reference(self):
        """Order can be created without a reference."""
        order = Order.objects.create(placed_by=self.user)
        self.assertIsNone(order.reference)
        self.assertIsNone(order.notes)

    def test_order_str_with_reference(self):
        """Order __str__ includes reference when present."""
        order = Order.objects.create(reference='Ticket 42', placed_by=self.user)
        self.assertIn('Ticket 42', str(order))

    def test_order_str_without_reference(self):
        """Order __str__ shows 'no ref' when no reference."""
        order = Order.objects.create(placed_by=self.user)
        self.assertIn('no ref', str(order))

    def test_order_ordering_most_recent_first(self):
        """Orders are ordered by -placed_at (most recent first)."""
        order1 = Order.objects.create(reference='First', placed_by=self.user)
        order2 = Order.objects.create(reference='Second', placed_by=self.user)
        orders = list(Order.objects.all())
        self.assertEqual(orders[0], order2)
        self.assertEqual(orders[1], order1)


class OrderLineModelTests(TransactionTestCase):
    """Tests for OrderLine model."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='testuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.recipe = Recipe.objects.create(
            name='Tomato Soup',
            yields_quantity=Decimal('10.0000'),
            yields_unit=self.portion_unit,
            selling_price=Decimal('5.99'),
            created_by=self.user,
        )
        self.order = Order.objects.create(
            reference='Table 1',
            placed_by=self.user,
        )

    def test_orderline_creation(self):
        """OrderLine can be created with required fields."""
        line = OrderLine.objects.create(
            order=self.order,
            recipe=self.recipe,
            quantity=2,
            unit_selling_price_snapshot=Decimal('5.99'),
        )
        self.assertEqual(line.order, self.order)
        self.assertEqual(line.recipe, self.recipe)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.unit_selling_price_snapshot, Decimal('5.99'))

    def test_orderline_str(self):
        """OrderLine __str__ shows quantity x recipe name."""
        line = OrderLine.objects.create(
            order=self.order,
            recipe=self.recipe,
            quantity=3,
        )
        self.assertEqual(str(line), '3 x Tomato Soup')

    def test_orderline_allows_null_selling_price_snapshot(self):
        """OrderLine allows null unit_selling_price_snapshot."""
        recipe_no_price = Recipe.objects.create(
            name='Mystery Dish',
            yields_quantity=Decimal('1.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        line = OrderLine.objects.create(
            order=self.order,
            recipe=recipe_no_price,
            quantity=1,
            unit_selling_price_snapshot=None,
        )
        self.assertIsNone(line.unit_selling_price_snapshot)

    def test_orderline_cascade_delete_with_order(self):
        """Deleting Order cascades to OrderLine."""
        line = OrderLine.objects.create(
            order=self.order,
            recipe=self.recipe,
            quantity=1,
        )
        line_pk = line.pk
        self.order.delete()
        self.assertFalse(OrderLine.objects.filter(pk=line_pk).exists())

    def test_orderline_protects_recipe_deletion(self):
        """Cannot delete Recipe that has OrderLines (PROTECT)."""
        OrderLine.objects.create(
            order=self.order,
            recipe=self.recipe,
            quantity=1,
        )
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.recipe.delete()


class OrderLineQuantityValidatorTests(TransactionTestCase):
    """Tests for OrderLine.quantity MinValueValidator(1)."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='testuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.recipe = Recipe.objects.create(
            name='Tomato Soup',
            yields_quantity=Decimal('10.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        self.order = Order.objects.create(placed_by=self.user)

    def test_quantity_zero_fails_validation(self):
        """OrderLine with quantity=0 fails full_clean validation."""
        line = OrderLine(
            order=self.order,
            recipe=self.recipe,
            quantity=0,
        )
        with self.assertRaises(ValidationError) as ctx:
            line.full_clean()
        self.assertIn('quantity', ctx.exception.message_dict)

    def test_quantity_one_passes_validation(self):
        """OrderLine with quantity=1 passes full_clean validation."""
        line = OrderLine(
            order=self.order,
            recipe=self.recipe,
            quantity=1,
        )
        line.full_clean()

    def test_quantity_positive_passes_validation(self):
        """OrderLine with quantity > 1 passes full_clean validation."""
        line = OrderLine(
            order=self.order,
            recipe=self.recipe,
            quantity=99,
        )
        line.full_clean()


class SaleMovementTypeTests(TestCase):
    """Tests for SALE movement type in StockMovement."""

    def test_sale_in_movement_type_choices(self):
        """SALE is a valid movement type choice."""
        choices = dict(StockMovement.MOVEMENT_TYPE_CHOICES)
        self.assertIn('SALE', choices)
        self.assertEqual(choices['SALE'], 'Sale')

    def test_stockmovement_can_have_sale_type(self):
        """StockMovement can be created with movement_type=SALE."""
        kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        category = Category.objects.create(name='Produce', is_active=True)
        product = Product.objects.create(
            name='Tomatoes',
            category=category,
            unit=kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        movement = StockMovement.objects.create(
            product=product,
            quantity=Decimal('1.0000'),
            movement_type='SALE',
        )
        self.assertEqual(movement.movement_type, 'SALE')


class OrderAuditlogTests(TransactionTestCase):
    """Tests for auditlog tracking on Order and OrderLine."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='testuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.recipe = Recipe.objects.create(
            name='Tomato Soup',
            yields_quantity=Decimal('10.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )

    def test_order_creation_logged(self):
        """Creating an Order writes an auditlog LogEntry with action=CREATE."""
        order = Order.objects.create(
            reference='Table 7',
            placed_by=self.user,
        )

        log_entries = LogEntry.objects.filter(
            content_type__model='order',
            object_pk=str(order.pk),
        )

        self.assertEqual(log_entries.count(), 1)
        entry = log_entries.first()
        self.assertEqual(entry.action, LogEntry.Action.CREATE)

    def test_orderline_creation_logged(self):
        """Creating an OrderLine writes an auditlog LogEntry with action=CREATE."""
        order = Order.objects.create(placed_by=self.user)
        line = OrderLine.objects.create(
            order=order,
            recipe=self.recipe,
            quantity=2,
            unit_selling_price_snapshot=Decimal('5.99'),
        )

        log_entries = LogEntry.objects.filter(
            content_type__model='orderline',
            object_pk=str(line.pk),
        )

        self.assertEqual(log_entries.count(), 1)
        entry = log_entries.first()
        self.assertEqual(entry.action, LogEntry.Action.CREATE)
