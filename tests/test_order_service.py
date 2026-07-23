"""
Tests for order placement service (F15b).

Tests cover:
- Happy path: single-line order depletes ingredients correctly
- Multi-line: order with multiple recipes depletes all ingredients
- Block-on-short: insufficient stock rolls back entire order
- Unit mismatch: ingredient unit type mismatch blocks order
- Missing price fail-soft: order succeeds with null cost snapshot
- Invalid input: empty order, zero portions, recipe with no ingredients
- SALE movement type: record_movement accepts SALE and decrements stock
"""

from decimal import Decimal

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model

from inventory.models import Product, Category, Unit, StockMovement, Order, OrderLine
from inventory.services import (
    record_movement,
    place_order,
    OrderError,
    InsufficientStockError,
    UnitTypeMismatchError,
    StockValidationError,
)
from recipes.models import Recipe, RecipeIngredient
from costing.services import set_product_price

CustomUser = get_user_model()


class RecordMovementSaleTests(TransactionTestCase):
    """Tests for SALE movement type in record_movement."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        set_product_price(self.product, Decimal('5.00'), self.user)

    def test_sale_decrements_stock(self):
        """SALE movement decrements product stock."""
        initial_stock = self.product.stock_quantity
        movement = record_movement(
            product=self.product,
            movement_type='SALE',
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('2.0000'))
        self.assertEqual(movement.movement_type, 'SALE')
        self.assertEqual(movement.quantity, Decimal('2.0000'))

    def test_sale_blocks_negative_stock(self):
        """SALE that would make stock negative raises InsufficientStockError."""
        with self.assertRaises(InsufficientStockError):
            record_movement(
                product=self.product,
                movement_type='SALE',
                quantity=Decimal('100.0000'),
                unit=self.kg_unit,
                user=self.user,
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('10.0000'))

    def test_sale_stamps_cost_snapshot(self):
        """SALE movement stamps unit_cost_snapshot from current price."""
        movement = record_movement(
            product=self.product,
            movement_type='SALE',
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        self.assertEqual(movement.unit_cost_snapshot, Decimal('5.00'))

    def test_sale_with_reference_id(self):
        """SALE movement can carry reference_id."""
        movement = record_movement(
            product=self.product,
            movement_type='SALE',
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            user=self.user,
            reference_id='order-123',
        )
        self.assertEqual(movement.reference_id, 'order-123')


class PlaceOrderHappyPathTests(TransactionTestCase):
    """Tests for successful order placement."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.g_unit = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.chicken = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        set_product_price(self.chicken, Decimal('5.00'), self.user)

        self.recipe = Recipe.objects.create(
            name='Chicken Soup',
            yields_quantity=Decimal('4.0000'),
            yields_unit=self.portion_unit,
            selling_price=Decimal('8.50'),
            created_by=self.user,
        )
        # Recipe uses 400g chicken to make 4 portions (100g per portion)
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.chicken,
            quantity=Decimal('400.0000'),
            unit=self.g_unit,
        )

    def test_single_line_order_depletes_correctly(self):
        """Single-line order depletes ingredients by scaled quantity."""
        initial_stock = self.chicken.stock_quantity

        order = place_order(
            lines_data=[(self.recipe, 2)],
            user=self.user,
            reference='Table 5',
        )

        # Check order created
        self.assertIsNotNone(order.pk)
        self.assertEqual(order.reference, 'Table 5')
        self.assertEqual(order.placed_by, self.user)

        # Check order line
        lines = list(order.lines.all())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].recipe, self.recipe)
        self.assertEqual(lines[0].quantity, 2)
        self.assertEqual(lines[0].unit_selling_price_snapshot, Decimal('8.50'))

        # Check stock depletion: 2 portions / 4 yield * 400g = 200g = 0.2kg
        self.chicken.refresh_from_db()
        expected_depletion = Decimal('0.2000')  # 200g in kg
        self.assertEqual(
            self.chicken.stock_quantity,
            initial_stock - expected_depletion
        )

        # Check SALE movement
        sale_movements = StockMovement.objects.filter(
            movement_type='SALE',
            reference_id=f'order-{order.pk}',
        )
        self.assertEqual(sale_movements.count(), 1)
        sale = sale_movements.first()
        self.assertEqual(sale.product, self.chicken)
        self.assertEqual(sale.quantity, expected_depletion)
        self.assertEqual(sale.unit_cost_snapshot, Decimal('5.00'))


class PlaceOrderMultiLineTests(TransactionTestCase):
    """Tests for multi-line order placement."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)

        self.chicken = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.rice = Product.objects.create(
            name='Rice',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('20.0000'),
        )

        self.recipe1 = Recipe.objects.create(
            name='Chicken Dish',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe1,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

        self.recipe2 = Recipe.objects.create(
            name='Rice Dish',
            yields_quantity=Decimal('4.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe2,
            product=self.rice,
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
        )

    def test_multi_line_depletes_all_ingredients(self):
        """Multi-line order depletes ingredients from all recipes."""
        initial_chicken = self.chicken.stock_quantity
        initial_rice = self.rice.stock_quantity

        order = place_order(
            lines_data=[
                (self.recipe1, 2),  # 2 portions / 2 yield * 1kg = 1kg chicken
                (self.recipe2, 2),  # 2 portions / 4 yield * 2kg = 1kg rice
            ],
            user=self.user,
        )

        self.chicken.refresh_from_db()
        self.rice.refresh_from_db()

        self.assertEqual(self.chicken.stock_quantity, initial_chicken - Decimal('1.0000'))
        self.assertEqual(self.rice.stock_quantity, initial_rice - Decimal('1.0000'))

        # All SALE movements carry the order reference
        sale_movements = StockMovement.objects.filter(
            movement_type='SALE',
            reference_id=f'order-{order.pk}',
        )
        self.assertEqual(sale_movements.count(), 2)


class PlaceOrderBlockOnShortTests(TransactionTestCase):
    """Tests for all-or-nothing rollback on insufficient stock."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)

        self.chicken = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.rare_spice = Product.objects.create(
            name='Rare Spice',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('0.1000'),  # Very limited stock
        )

        # First recipe uses chicken (plentiful)
        self.recipe1 = Recipe.objects.create(
            name='Chicken Dish',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe1,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

        # Second recipe uses rare spice (will be short)
        self.recipe2 = Recipe.objects.create(
            name='Spicy Dish',
            yields_quantity=Decimal('1.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe2,
            product=self.rare_spice,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

    def test_block_on_short_rolls_back_entire_order(self):
        """When second line is short, entire order is rolled back."""
        initial_chicken = self.chicken.stock_quantity
        initial_spice = self.rare_spice.stock_quantity
        initial_order_count = Order.objects.count()
        initial_line_count = OrderLine.objects.count()
        initial_sale_count = StockMovement.objects.filter(movement_type='SALE').count()

        with self.assertRaises(InsufficientStockError):
            place_order(
                lines_data=[
                    (self.recipe1, 2),  # Would succeed
                    (self.recipe2, 1),  # Will fail - needs 1kg, only 0.1kg available
                ],
                user=self.user,
            )

        # NO Order created
        self.assertEqual(Order.objects.count(), initial_order_count)

        # NO OrderLine created
        self.assertEqual(OrderLine.objects.count(), initial_line_count)

        # NO SALE movement created
        self.assertEqual(
            StockMovement.objects.filter(movement_type='SALE').count(),
            initial_sale_count
        )

        # FIRST product's stock is UNCHANGED (full rollback)
        self.chicken.refresh_from_db()
        self.assertEqual(self.chicken.stock_quantity, initial_chicken)

        # Second product's stock is also unchanged
        self.rare_spice.refresh_from_db()
        self.assertEqual(self.rare_spice.stock_quantity, initial_spice)


class PlaceOrderUnitMismatchTests(TransactionTestCase):
    """Tests for unit type mismatch blocking order."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.litre_unit = Unit.objects.create(
            name='Litres',
            unit_type='VOLUME',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='millilitres',
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)

        # Product measured in kg
        self.chicken = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )

        # Recipe ingredient incorrectly uses litres for chicken
        self.recipe = Recipe.objects.create(
            name='Bad Recipe',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.litre_unit,  # Wrong unit type!
        )

    def test_unit_mismatch_blocks_and_rolls_back(self):
        """Unit type mismatch raises UnitTypeMismatchError and rolls back."""
        initial_stock = self.chicken.stock_quantity
        initial_order_count = Order.objects.count()

        with self.assertRaises(UnitTypeMismatchError):
            place_order(
                lines_data=[(self.recipe, 1)],
                user=self.user,
            )

        # Order not created
        self.assertEqual(Order.objects.count(), initial_order_count)

        # Stock unchanged
        self.chicken.refresh_from_db()
        self.assertEqual(self.chicken.stock_quantity, initial_stock)


class PlaceOrderMissingPriceTests(TransactionTestCase):
    """Tests for fail-soft behavior when product has no price."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)

        # Product with NO price set
        self.chicken = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )

        self.recipe = Recipe.objects.create(
            name='Chicken Dish',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

    def test_missing_price_order_succeeds_with_null_snapshot(self):
        """Order succeeds when product has no price; SALE has null cost snapshot."""
        order = place_order(
            lines_data=[(self.recipe, 2)],
            user=self.user,
        )

        # Order created
        self.assertIsNotNone(order.pk)

        # Stock depleted
        self.chicken.refresh_from_db()
        self.assertEqual(self.chicken.stock_quantity, Decimal('9.0000'))

        # SALE movement has null cost snapshot
        sale = StockMovement.objects.get(
            movement_type='SALE',
            reference_id=f'order-{order.pk}',
        )
        self.assertIsNone(sale.unit_cost_snapshot)


class PlaceOrderInvalidInputTests(TransactionTestCase):
    """Tests for invalid input validation."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.portion_unit = Unit.objects.create(
            name='Portions',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.chicken = Product.objects.create(
            name='Chicken',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )

    def test_empty_order_raises_order_error(self):
        """Empty lines_data raises OrderError."""
        with self.assertRaises(OrderError) as ctx:
            place_order(lines_data=[], user=self.user)
        self.assertIn('at least one line', str(ctx.exception))

    def test_zero_portions_raises_order_error(self):
        """Zero portions raises OrderError."""
        recipe = Recipe.objects.create(
            name='Test Recipe',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=recipe,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

        with self.assertRaises(OrderError) as ctx:
            place_order(lines_data=[(recipe, 0)], user=self.user)
        self.assertIn('positive integer', str(ctx.exception))

    def test_negative_portions_raises_order_error(self):
        """Negative portions raises OrderError."""
        recipe = Recipe.objects.create(
            name='Test Recipe',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=recipe,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

        with self.assertRaises(OrderError) as ctx:
            place_order(lines_data=[(recipe, -1)], user=self.user)
        self.assertIn('positive integer', str(ctx.exception))

    def test_recipe_with_no_ingredients_raises_order_error(self):
        """Recipe with no ingredients raises OrderError."""
        empty_recipe = Recipe.objects.create(
            name='Empty Recipe',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )

        with self.assertRaises(OrderError) as ctx:
            place_order(lines_data=[(empty_recipe, 1)], user=self.user)
        self.assertIn('no ingredients', str(ctx.exception))

    def test_recipe_with_zero_yield_raises_order_error(self):
        """Recipe with zero yields_quantity raises OrderError."""
        bad_recipe = Recipe.objects.create(
            name='Bad Yield Recipe',
            yields_quantity=Decimal('0.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=bad_recipe,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

        with self.assertRaises(OrderError) as ctx:
            place_order(lines_data=[(bad_recipe, 1)], user=self.user)
        self.assertIn('invalid yield', str(ctx.exception))

    def test_invalid_input_does_not_touch_stock(self):
        """Invalid input validation happens before any stock mutation."""
        initial_stock = self.chicken.stock_quantity

        # Create valid recipe first
        recipe = Recipe.objects.create(
            name='Valid Recipe',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=recipe,
            product=self.chicken,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
        )

        # Empty recipe that will fail validation
        empty_recipe = Recipe.objects.create(
            name='Empty Recipe',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion_unit,
            created_by=self.user,
        )

        with self.assertRaises(OrderError):
            place_order(
                lines_data=[
                    (recipe, 2),       # Valid
                    (empty_recipe, 1), # Invalid - no ingredients
                ],
                user=self.user,
            )

        # Stock unchanged (validation failed before any mutation)
        self.chicken.refresh_from_db()
        self.assertEqual(self.chicken.stock_quantity, initial_stock)
