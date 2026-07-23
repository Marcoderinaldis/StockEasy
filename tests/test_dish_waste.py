"""
Tests for dish waste functionality (F15d).

Tests cover:
- Whole dish waste (all ingredients)
- Partial dish waste (subset of ingredients)
- All-or-nothing rollback on insufficient stock
- New waste categories
- Validation errors
- Missing price fail-soft behaviour
- F13 analytics integration
- Backwards compatibility of record_waste
"""

from decimal import Decimal

from django.test import TestCase, TransactionTestCase

from accounts.models import CustomUser
from inventory.models import (
    Category, Product, Unit, StockMovement, PurchasePrice,
)
from recipes.models import Recipe, RecipeIngredient
from waste.models import WasteRecord
from waste.services import (
    record_waste,
    record_dish_waste,
    valued_waste_summary,
    StockValidationError,
    InsufficientStockError,
)


class DishWasteTestBase(TransactionTestCase):
    """Base class with common setup for dish waste tests."""

    def setUp(self):
        # Create user
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

        # Create units
        self.gram = Unit.objects.create(
            name='Grams',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='grams',
        )
        self.ml = Unit.objects.create(
            name='Millilitres',
            unit_type='VOLUME',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='millilitres',
        )
        self.portion = Unit.objects.create(
            name='Portion',
            unit_type='COUNT',
            conversion_to_base=Decimal('1.0000'),
            base_unit_name='count',
        )

        # Create category
        self.category = Category.objects.create(name='Ingredients', is_active=True)

        # Create products with stock
        self.product_a = Product.objects.create(
            name='Product A',
            category=self.category,
            unit=self.gram,
            stock_quantity=Decimal('1000.0000'),  # 1kg
            is_active=True,
        )
        self.product_b = Product.objects.create(
            name='Product B',
            category=self.category,
            unit=self.ml,
            stock_quantity=Decimal('500.0000'),  # 500ml
            is_active=True,
        )

        # Create prices
        PurchasePrice.objects.create(
            product=self.product_a,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.user,
        )
        PurchasePrice.objects.create(
            product=self.product_b,
            unit_price=Decimal('3.50'),
            currency='GBP',
            created_by=self.user,
        )

        # Create recipe yielding 4 portions with:
        # - 400g of Product A
        # - 200ml of Product B
        self.recipe = Recipe.objects.create(
            name='Test Dish',
            yields_quantity=Decimal('4.0000'),
            yields_unit=self.portion,
            created_by=self.user,
        )
        self.ingredient_a = RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.product_a,
            quantity=Decimal('400.0000'),
            unit=self.gram,
        )
        self.ingredient_b = RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.product_b,
            quantity=Decimal('200.0000'),
            unit=self.ml,
        )


class WholeDishWasteTests(DishWasteTestBase):
    """Tests for wasting a whole dish (all ingredients)."""

    def test_whole_dish_waste_two_portions(self):
        """Wasting 2 portions of 4-portion recipe depletes half of each ingredient."""
        initial_stock_a = self.product_a.stock_quantity
        initial_stock_b = self.product_b.stock_quantity

        records = record_dish_waste(
            recipe=self.recipe,
            portions=2,
            waste_category='Prepared dish wasted',
            user=self.user,
        )

        # Should create two WasteRecords
        self.assertEqual(len(records), 2)

        # Refresh from DB
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()

        # 2 portions / 4 yield = 0.5 scale
        # Product A: 400g * 0.5 = 200g wasted
        # Product B: 200ml * 0.5 = 100ml wasted
        expected_waste_a = Decimal('200.0000')
        expected_waste_b = Decimal('100.0000')

        self.assertEqual(
            self.product_a.stock_quantity,
            initial_stock_a - expected_waste_a
        )
        self.assertEqual(
            self.product_b.stock_quantity,
            initial_stock_b - expected_waste_b
        )

        # Check movements have same reference_id
        movements = StockMovement.objects.filter(movement_type='WASTE').order_by('id')
        self.assertEqual(movements.count(), 2)

        ref_ids = set(m.reference_id for m in movements)
        self.assertEqual(len(ref_ids), 1)  # All same reference
        ref_id = list(ref_ids)[0]
        self.assertTrue(ref_id.startswith('dish-waste-'))
        self.assertLessEqual(len(ref_id), 50)

        # Check quantities on movements
        movement_a = movements.get(product=self.product_a)
        movement_b = movements.get(product=self.product_b)
        self.assertEqual(movement_a.quantity, expected_waste_a)
        self.assertEqual(movement_b.quantity, expected_waste_b)

        # Check category on movements
        self.assertEqual(movement_a.reason_category, 'Prepared dish wasted')
        self.assertEqual(movement_b.reason_category, 'Prepared dish wasted')

    def test_whole_dish_waste_returns_waste_records(self):
        """record_dish_waste returns list of WasteRecord objects."""
        records = record_dish_waste(
            recipe=self.recipe,
            portions=1,
            waste_category='Preparation error',
            user=self.user,
        )

        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 2)
        for rec in records:
            self.assertIsInstance(rec, WasteRecord)


class PartialDishWasteTests(DishWasteTestBase):
    """Tests for partial dish waste (subset of ingredients)."""

    def test_partial_waste_single_ingredient(self):
        """Partial waste with only one ingredient leaves others untouched."""
        initial_stock_a = self.product_a.stock_quantity
        initial_stock_b = self.product_b.stock_quantity

        records = record_dish_waste(
            recipe=self.recipe,
            portions=2,
            waste_category='Preparation error',
            user=self.user,
            ingredients=[self.ingredient_a],  # Only Product A
        )

        # Should create one WasteRecord
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].product, self.product_a)

        # Refresh from DB
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()

        # Product A: 400g * 0.5 = 200g wasted
        expected_waste_a = Decimal('200.0000')
        self.assertEqual(
            self.product_a.stock_quantity,
            initial_stock_a - expected_waste_a
        )

        # Product B should be UNCHANGED
        self.assertEqual(self.product_b.stock_quantity, initial_stock_b)

        # Only one movement
        movements = StockMovement.objects.filter(movement_type='WASTE')
        self.assertEqual(movements.count(), 1)
        self.assertEqual(movements[0].product, self.product_a)


class AllOrNothingTests(DishWasteTestBase):
    """Tests for all-or-nothing rollback behaviour."""

    def test_rollback_when_second_ingredient_short(self):
        """If second ingredient is short, entire dish waste rolls back."""
        # Set Product B to very low stock
        self.product_b.stock_quantity = Decimal('10.0000')  # Only 10ml
        self.product_b.save()

        initial_stock_a = self.product_a.stock_quantity
        initial_stock_b = self.product_b.stock_quantity
        initial_movement_count = StockMovement.objects.filter(
            movement_type='WASTE'
        ).count()
        initial_record_count = WasteRecord.objects.count()

        # Try to waste 2 portions (needs 100ml of B, but only 10ml available)
        with self.assertRaises(InsufficientStockError):
            record_dish_waste(
                recipe=self.recipe,
                portions=2,
                waste_category='Prepared dish wasted',
                user=self.user,
            )

        # Refresh from DB
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()

        # BOTH stocks should be UNCHANGED
        self.assertEqual(self.product_a.stock_quantity, initial_stock_a)
        self.assertEqual(self.product_b.stock_quantity, initial_stock_b)

        # NO new movements or records
        self.assertEqual(
            StockMovement.objects.filter(movement_type='WASTE').count(),
            initial_movement_count
        )
        self.assertEqual(WasteRecord.objects.count(), initial_record_count)


class NewCategoriesTests(DishWasteTestBase):
    """Tests for the two new waste categories."""

    def test_prepared_dish_wasted_category(self):
        """'Prepared dish wasted' category is valid and stored correctly."""
        records = record_dish_waste(
            recipe=self.recipe,
            portions=1,
            waste_category='Prepared dish wasted',
            user=self.user,
        )

        for rec in records:
            self.assertEqual(rec.waste_category, 'Prepared dish wasted')
            self.assertEqual(
                rec.stock_movement.reason_category,
                'Prepared dish wasted'
            )

    def test_preparation_error_category(self):
        """'Preparation error' category is valid and stored correctly."""
        records = record_dish_waste(
            recipe=self.recipe,
            portions=1,
            waste_category='Preparation error',
            user=self.user,
        )

        for rec in records:
            self.assertEqual(rec.waste_category, 'Preparation error')
            self.assertEqual(
                rec.stock_movement.reason_category,
                'Preparation error'
            )

    def test_new_categories_in_choices(self):
        """New categories are in REASON_CATEGORY_CHOICES."""
        choices = dict(StockMovement.REASON_CATEGORY_CHOICES)
        self.assertIn('Prepared dish wasted', choices)
        self.assertIn('Preparation error', choices)


class ValidationTests(DishWasteTestBase):
    """Tests for input validation errors."""

    def test_zero_portions_raises(self):
        """Zero portions raises StockValidationError."""
        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=0,
                waste_category='Prepared dish wasted',
                user=self.user,
            )
        self.assertIn('positive integer', str(ctx.exception))

    def test_negative_portions_raises(self):
        """Negative portions raises StockValidationError."""
        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=-1,
                waste_category='Prepared dish wasted',
                user=self.user,
            )
        self.assertIn('positive integer', str(ctx.exception))

    def test_empty_ingredients_list_raises(self):
        """Empty ingredients list raises StockValidationError."""
        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=1,
                waste_category='Prepared dish wasted',
                user=self.user,
                ingredients=[],
            )
        self.assertIn('cannot be empty', str(ctx.exception))

    def test_ingredient_from_different_recipe_raises(self):
        """Ingredient from different recipe raises StockValidationError."""
        # Create another recipe with its own ingredient
        other_recipe = Recipe.objects.create(
            name='Other Dish',
            yields_quantity=Decimal('2.0000'),
            yields_unit=self.portion,
            created_by=self.user,
        )
        other_ingredient = RecipeIngredient.objects.create(
            recipe=other_recipe,
            product=self.product_a,
            quantity=Decimal('100.0000'),
            unit=self.gram,
        )

        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=1,
                waste_category='Prepared dish wasted',
                user=self.user,
                ingredients=[other_ingredient],
            )
        self.assertIn('does not belong', str(ctx.exception))

    def test_missing_category_raises(self):
        """Missing waste category raises StockValidationError."""
        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=1,
                waste_category='',
                user=self.user,
            )
        self.assertIn('required', str(ctx.exception))

    def test_blank_category_raises(self):
        """Blank waste category raises StockValidationError."""
        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=1,
                waste_category='   ',
                user=self.user,
            )
        self.assertIn('required', str(ctx.exception))

    def test_zero_yield_raises(self):
        """Recipe with zero yield raises StockValidationError."""
        self.recipe.yields_quantity = Decimal('0')
        self.recipe.save()

        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=self.recipe,
                portions=1,
                waste_category='Prepared dish wasted',
                user=self.user,
            )
        self.assertIn('invalid yield', str(ctx.exception))

    def test_recipe_with_no_ingredients_raises(self):
        """Recipe with no ingredients raises StockValidationError."""
        # Create empty recipe
        empty_recipe = Recipe.objects.create(
            name='Empty Dish',
            yields_quantity=Decimal('4.0000'),
            yields_unit=self.portion,
            created_by=self.user,
        )

        with self.assertRaises(StockValidationError) as ctx:
            record_dish_waste(
                recipe=empty_recipe,
                portions=1,
                waste_category='Prepared dish wasted',
                user=self.user,
            )
        self.assertIn('no ingredients', str(ctx.exception))

    def test_validation_does_not_touch_stock(self):
        """Validation errors leave stock unchanged."""
        initial_stock_a = self.product_a.stock_quantity

        with self.assertRaises(StockValidationError):
            record_dish_waste(
                recipe=self.recipe,
                portions=0,
                waste_category='Prepared dish wasted',
                user=self.user,
            )

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, initial_stock_a)


class MissingPriceTests(DishWasteTestBase):
    """Tests for fail-soft behaviour when price is missing."""

    def test_missing_price_still_records_waste(self):
        """Dish waste succeeds even if ingredient has no price."""
        # Remove price from Product A
        PurchasePrice.objects.filter(product=self.product_a).update(
            effective_to='2020-01-01'
        )

        initial_stock_a = self.product_a.stock_quantity

        records = record_dish_waste(
            recipe=self.recipe,
            portions=1,
            waste_category='Prepared dish wasted',
            user=self.user,
        )

        self.assertEqual(len(records), 2)

        # Stock was still decremented
        self.product_a.refresh_from_db()
        self.assertLess(self.product_a.stock_quantity, initial_stock_a)

        # Movement for Product A has None snapshot
        movement_a = StockMovement.objects.get(
            product=self.product_a,
            movement_type='WASTE'
        )
        self.assertIsNone(movement_a.unit_cost_snapshot)

        # Movement for Product B has valid snapshot
        movement_b = StockMovement.objects.get(
            product=self.product_b,
            movement_type='WASTE'
        )
        self.assertIsNotNone(movement_b.unit_cost_snapshot)
        self.assertEqual(movement_b.unit_cost_snapshot, Decimal('3.50'))


class F13IntegrationTests(DishWasteTestBase):
    """Tests for F13 valued wastage analytics integration."""

    def test_dish_waste_appears_in_valued_waste_summary(self):
        """Dish waste movements appear in valued_waste_summary."""
        record_dish_waste(
            recipe=self.recipe,
            portions=2,
            waste_category='Prepared dish wasted',
            user=self.user,
        )

        summary = valued_waste_summary()

        # Should have valued waste
        self.assertGreater(summary['valued_event_count'], 0)
        self.assertGreater(summary['valued_total'], Decimal('0'))

    def test_new_category_shows_in_by_category(self):
        """New category shows as its own row in by_category."""
        record_dish_waste(
            recipe=self.recipe,
            portions=2,
            waste_category='Prepared dish wasted',
            user=self.user,
        )

        # Need enough events to pass k-anonymity threshold
        record_dish_waste(
            recipe=self.recipe,
            portions=1,
            waste_category='Prepared dish wasted',
            user=self.user,
        )
        record_dish_waste(
            recipe=self.recipe,
            portions=1,
            waste_category='Prepared dish wasted',
            user=self.user,
        )

        summary = valued_waste_summary()

        # Find the category in by_category
        categories = {row['reason_category']: row for row in summary['by_category']}

        # With 3 dish wastes * 2 ingredients each = 6 events, should pass k-anon
        # and show as its own row
        self.assertIn('Prepared dish wasted', categories)


class RecordWasteBackwardsCompatibilityTests(TransactionTestCase):
    """Tests for record_waste backwards compatibility."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='staffuser2',
            password='testpass123',
            role=CustomUser.Role.STAFF,
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
            stock_quantity=Decimal('1000.0000'),
            is_active=True,
        )

    def test_record_waste_without_reference_id(self):
        """record_waste works without reference_id parameter."""
        record = record_waste(
            product=self.product,
            quantity=Decimal('100'),
            unit=self.gram,
            waste_category='Other',
            user=self.user,
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.stock_movement.reference_id, None)

    def test_record_waste_with_reference_id(self):
        """record_waste works with reference_id parameter."""
        record = record_waste(
            product=self.product,
            quantity=Decimal('100'),
            unit=self.gram,
            waste_category='Other',
            user=self.user,
            reference_id='test-ref-123',
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.stock_movement.reference_id, 'test-ref-123')

    def test_record_waste_with_notes_and_reference_id(self):
        """record_waste works with both notes and reference_id."""
        record = record_waste(
            product=self.product,
            quantity=Decimal('100'),
            unit=self.gram,
            waste_category='Other',
            user=self.user,
            notes='Test note',
            reference_id='test-ref-456',
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.notes, 'Test note')
        self.assertEqual(record.stock_movement.reference_id, 'test-ref-456')
