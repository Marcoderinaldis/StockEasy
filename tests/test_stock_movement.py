"""
Tests for stock movement recording (Unit 3).

Tests cover:
- Service layer: record_movement, unit conversion, insufficient stock, atomic transactions
- View/RBAC: staff_required decorator, form submission, error handling
- Form: validation rules, reason required for OUT, movement type restrictions
"""

from decimal import Decimal

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import path, reverse, include
from django.contrib.auth import get_user_model
from django.http import HttpResponse

from inventory.models import Product, Category, Unit, StockMovement
from inventory.services import (
    record_movement,
    record_stock_in,
    record_stock_out,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
    convert_quantity_between_units,
)
from inventory.forms import StockMovementForm

CustomUser = get_user_model()


class ServiceRecordMovementTests(TransactionTestCase):
    """Tests for the record_movement service function."""

    def setUp(self):
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
        self.litre_unit = Unit.objects.create(
            name='Litres',
            unit_type='VOLUME',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='millilitres',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

    def test_in_increases_stock(self):
        """Valid IN movement increases product stock."""
        initial_stock = self.product.stock_quantity
        movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock + Decimal('5.0000'))
        self.assertEqual(movement.movement_type, 'IN')
        self.assertEqual(movement.quantity, Decimal('5.0000'))

    def test_out_decreases_stock(self):
        """Valid OUT movement decreases product stock."""
        initial_stock = self.product.stock_quantity
        movement = record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('3.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('3.0000'))
        self.assertEqual(movement.movement_type, 'OUT')

    def test_unit_conversion_on_in(self):
        """IN movement converts quantity from input unit to product unit."""
        initial_stock = self.product.stock_quantity
        movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('500.0000'),
            unit=self.g_unit,
            user=self.user,
        )
        self.product.refresh_from_db()
        expected_increase = Decimal('0.5000')
        self.assertEqual(self.product.stock_quantity, initial_stock + expected_increase)
        self.assertEqual(movement.quantity, expected_increase)

    def test_unit_mismatch_rejected(self):
        """Unit type mismatch raises UnitTypeMismatchError."""
        with self.assertRaises(UnitTypeMismatchError):
            record_movement(
                product=self.product,
                movement_type='IN',
                quantity=Decimal('1.0000'),
                unit=self.litre_unit,
                user=self.user,
            )

    def test_out_overdraw_rejected(self):
        """OUT that would make stock negative is rejected."""
        with self.assertRaises(InsufficientStockError):
            record_movement(
                product=self.product,
                movement_type='OUT',
                quantity=Decimal('100.0000'),
                unit=self.kg_unit,
                reason_category='Other',
                user=self.user,
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('10.0000'))

    def test_recorded_by_stamped(self):
        """Movement has recorded_by set to the user."""
        movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        self.assertEqual(movement.recorded_by, self.user)

    def test_each_success_creates_new_movement(self):
        """Each successful call creates a new StockMovement row."""
        initial_count = StockMovement.objects.count()
        record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        self.assertEqual(StockMovement.objects.count(), initial_count + 2)

    def test_existing_movements_never_edited(self):
        """Existing StockMovement rows are never modified."""
        movement1 = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
            user=self.user,
        )
        original_quantity = movement1.quantity
        original_recorded_at = movement1.recorded_at

        record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.user,
        )

        movement1.refresh_from_db()
        self.assertEqual(movement1.quantity, original_quantity)
        self.assertEqual(movement1.recorded_at, original_recorded_at)

    def test_sequential_outs_respect_available_stock(self):
        """Two sequential OUTs: second blocked if it would overdraw."""
        record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('8.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('2.0000'))

        with self.assertRaises(InsufficientStockError):
            record_movement(
                product=self.product,
                movement_type='OUT',
                quantity=Decimal('5.0000'),
                unit=self.kg_unit,
                reason_category='Other',
                user=self.user,
            )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('2.0000'))

    def test_invalid_movement_type_rejected(self):
        """Movement type other than IN/OUT raises StockValidationError."""
        with self.assertRaises(StockValidationError):
            record_movement(
                product=self.product,
                movement_type='WASTE',
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                user=self.user,
            )

    def test_zero_quantity_rejected(self):
        """Zero quantity raises StockValidationError."""
        with self.assertRaises(StockValidationError):
            record_movement(
                product=self.product,
                movement_type='IN',
                quantity=Decimal('0'),
                unit=self.kg_unit,
                user=self.user,
            )

    def test_negative_quantity_rejected(self):
        """Negative quantity raises StockValidationError."""
        with self.assertRaises(StockValidationError):
            record_movement(
                product=self.product,
                movement_type='IN',
                quantity=Decimal('-1.0000'),
                unit=self.kg_unit,
                user=self.user,
            )


class UnitConversionTests(TestCase):
    """Tests for unit conversion function."""

    def setUp(self):
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
        self.litre_unit = Unit.objects.create(
            name='Litres',
            unit_type='VOLUME',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='millilitres',
        )

    def test_kg_to_grams(self):
        """1 kg = 1000 grams."""
        result = convert_quantity_between_units(Decimal('1'), self.kg_unit, self.g_unit)
        self.assertEqual(result, Decimal('1000'))

    def test_grams_to_kg(self):
        """500 grams = 0.5 kg."""
        result = convert_quantity_between_units(Decimal('500'), self.g_unit, self.kg_unit)
        self.assertEqual(result, Decimal('0.5'))

    def test_same_unit_no_change(self):
        """Same unit returns same quantity."""
        result = convert_quantity_between_units(Decimal('5.5'), self.kg_unit, self.kg_unit)
        self.assertEqual(result, Decimal('5.5'))

    def test_different_unit_types_raises(self):
        """Different unit types raises ValueError."""
        with self.assertRaises(ValueError):
            convert_quantity_between_units(Decimal('1'), self.kg_unit, self.litre_unit)


class FormValidationTests(TestCase):
    """Tests for StockMovementForm validation."""

    def setUp(self):
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
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )

    def test_reason_required_for_out(self):
        """Reason is required when movement_type is OUT."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'OUT',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'reason_category': '',
            'note': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('reason_category', form.errors)

    def test_reason_not_required_for_in(self):
        """Reason is not required when movement_type is IN."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'IN',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'reason_category': '',
            'note': '',
        })
        self.assertTrue(form.is_valid())

    def test_waste_not_valid_choice(self):
        """WASTE is not a valid movement_type choice."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'WASTE',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('movement_type', form.errors)

    def test_void_not_valid_choice(self):
        """VOID is not a valid movement_type choice."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'VOID',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('movement_type', form.errors)

    def test_adjustment_not_valid_choice(self):
        """ADJUSTMENT_IN is not a valid movement_type choice."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'ADJUSTMENT_IN',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('movement_type', form.errors)

    def test_note_max_length_enforced(self):
        """Note field max length is enforced."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'IN',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'note': 'x' * 201,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('note', form.errors)

    def test_unit_type_mismatch_rejected(self):
        """Form rejects unit type mismatch."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'IN',
            'quantity': '1.0000',
            'unit': self.litre_unit.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Unit type mismatch', str(form.errors))

    def test_positive_quantity_required(self):
        """Quantity must be positive."""
        form = StockMovementForm(data={
            'product': self.product.pk,
            'movement_type': 'IN',
            'quantity': '0',
            'unit': self.kg_unit.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)


class ViewRBACTests(TestCase):
    """Tests for view access control and functionality."""

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
            stock_quantity=Decimal('10.0000'),
        )
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('inventory:stock_movement_create')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_can_access(self):
        """Staff user can access the view."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_manager_can_access(self):
        """Manager user can access the view (via hierarchy)."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access(self):
        """Admin user can access the view (via hierarchy)."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_successful_post_redirects(self):
        """Successful POST redirects and creates movement."""
        self.client.login(username='staffuser', password='testpass123')
        initial_count = StockMovement.objects.count()
        initial_stock = self.product.stock_quantity

        response = self.client.post(self.url, {
            'product': self.product.pk,
            'movement_type': 'IN',
            'quantity': '5.0000',
            'unit': self.kg_unit.pk,
            'reason_category': '',
            'note': '',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockMovement.objects.count(), initial_count + 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock + Decimal('5.0000'))

    def test_failed_post_shows_error_no_mutation(self):
        """Failed POST shows error and does not mutate stock."""
        self.client.login(username='staffuser', password='testpass123')
        initial_count = StockMovement.objects.count()
        initial_stock = self.product.stock_quantity

        response = self.client.post(self.url, {
            'product': self.product.pk,
            'movement_type': 'OUT',
            'quantity': '100.0000',
            'unit': self.kg_unit.pk,
            'reason_category': 'Other',
            'note': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Insufficient stock')
        self.assertEqual(StockMovement.objects.count(), initial_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_out_without_reason_shows_error(self):
        """OUT without reason shows form error."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'movement_type': 'OUT',
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'reason_category': '',
            'note': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reason is required')
