"""
Tests for waste recording (Unit 5).

Tests cover:
- Service layer: record_waste, unit conversion, insufficient stock, atomic transactions
- View/RBAC: staff_required decorator, form submission, error handling
- Form: validation rules, waste_category required
- Atomicity: transaction rollback on failure
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from inventory.models import Product, Category, Unit, StockMovement
from waste.models import WasteRecord
from waste.services import (
    record_waste,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
)
from waste.forms import WasteRecordForm

CustomUser = get_user_model()


class ServiceRecordWasteTests(TransactionTestCase):
    """Tests for the record_waste service function."""

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

    def test_waste_decreases_stock(self):
        """Valid waste decrements product stock by the correct amount."""
        initial_stock = self.product.stock_quantity
        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('3.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('3.0000'))
        self.assertEqual(waste_record.quantity_wasted, Decimal('3.0000'))

    def test_waste_creates_both_records_linked(self):
        """Waste creates both WasteRecord AND linked WASTE StockMovement."""
        initial_waste_count = WasteRecord.objects.count()
        initial_movement_count = StockMovement.objects.count()

        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
            waste_category='Delivery damaged',
            user=self.user,
        )

        # Both records created
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count + 1)
        self.assertEqual(StockMovement.objects.count(), initial_movement_count + 1)

        # They are linked
        self.assertIsNotNone(waste_record.stock_movement)
        self.assertEqual(waste_record.stock_movement.movement_type, 'WASTE')
        self.assertEqual(waste_record.stock_movement.product, self.product)
        self.assertEqual(waste_record.stock_movement.quantity, Decimal('2.0000'))
        self.assertEqual(waste_record.stock_movement.reason_category, 'Delivery damaged')

        # Reverse relationship works
        self.assertEqual(waste_record.stock_movement.waste_record, waste_record)

    def test_waste_category_required(self):
        """waste_category is required - empty value rejected."""
        initial_stock = self.product.stock_quantity
        initial_waste_count = WasteRecord.objects.count()
        initial_movement_count = StockMovement.objects.count()

        with self.assertRaises(StockValidationError) as context:
            record_waste(
                product=self.product,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='',
                user=self.user,
            )

        self.assertIn('required', str(context.exception).lower())

        # Nothing written
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count)
        self.assertEqual(StockMovement.objects.count(), initial_movement_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_waste_category_required_whitespace_only(self):
        """waste_category with only whitespace is rejected."""
        with self.assertRaises(StockValidationError):
            record_waste(
                product=self.product,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='   ',
                user=self.user,
            )

    def test_unit_mismatch_rejected(self):
        """Unit type mismatch raises UnitTypeMismatchError, nothing written."""
        initial_stock = self.product.stock_quantity
        initial_waste_count = WasteRecord.objects.count()
        initial_movement_count = StockMovement.objects.count()

        with self.assertRaises(UnitTypeMismatchError):
            record_waste(
                product=self.product,
                quantity=Decimal('1.0000'),
                unit=self.litre_unit,
                waste_category='Other',
                user=self.user,
            )

        # Nothing written
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count)
        self.assertEqual(StockMovement.objects.count(), initial_movement_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_overdraw_blocked(self):
        """Waste that would make stock negative is rejected."""
        initial_stock = self.product.stock_quantity
        initial_waste_count = WasteRecord.objects.count()
        initial_movement_count = StockMovement.objects.count()

        with self.assertRaises(InsufficientStockError):
            record_waste(
                product=self.product,
                quantity=Decimal('100.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

        # Stock unchanged, nothing written
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count)
        self.assertEqual(StockMovement.objects.count(), initial_movement_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_unit_conversion_on_waste(self):
        """Waste converts quantity from input unit to product unit."""
        initial_stock = self.product.stock_quantity  # 10 kg

        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('500.0000'),  # 500 grams
            unit=self.g_unit,
            waste_category='Spillage/accidental waste',
            user=self.user,
        )

        self.product.refresh_from_db()
        # 500g = 0.5kg
        expected_decrease = Decimal('0.5000')
        self.assertEqual(self.product.stock_quantity, initial_stock - expected_decrease)
        self.assertEqual(waste_record.quantity_wasted, expected_decrease)
        self.assertEqual(waste_record.stock_movement.quantity, expected_decrease)

    def test_recorded_by_stamped_on_both(self):
        """recorded_by is set on both WasteRecord and StockMovement."""
        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            waste_category='Other',
            user=self.user,
        )

        self.assertEqual(waste_record.recorded_by, self.user)
        self.assertEqual(waste_record.stock_movement.recorded_by, self.user)

    def test_notes_stored(self):
        """Notes are stored on both WasteRecord and StockMovement."""
        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            waste_category='Other',
            user=self.user,
            notes='Test note',
        )

        self.assertEqual(waste_record.notes, 'Test note')
        self.assertEqual(waste_record.stock_movement.reason_notes, 'Test note')

    def test_zero_quantity_rejected(self):
        """Zero quantity raises StockValidationError."""
        with self.assertRaises(StockValidationError):
            record_waste(
                product=self.product,
                quantity=Decimal('0'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

    def test_negative_quantity_rejected(self):
        """Negative quantity raises StockValidationError."""
        with self.assertRaises(StockValidationError):
            record_waste(
                product=self.product,
                quantity=Decimal('-1.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

    def test_existing_movements_never_edited(self):
        """Existing StockMovement rows are never modified (append-only)."""
        movement1 = record_waste(
            product=self.product,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            waste_category='Other',
            user=self.user,
        ).stock_movement

        original_quantity = movement1.quantity
        original_recorded_at = movement1.recorded_at

        # Record another waste
        record_waste(
            product=self.product,
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.user,
        )

        movement1.refresh_from_db()
        self.assertEqual(movement1.quantity, original_quantity)
        self.assertEqual(movement1.recorded_at, original_recorded_at)

    def test_existing_waste_records_never_edited(self):
        """Existing WasteRecord rows are never modified (append-only)."""
        waste1 = record_waste(
            product=self.product,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            waste_category='Other',
            user=self.user,
        )

        original_quantity = waste1.quantity_wasted
        original_recorded_at = waste1.recorded_at

        # Record another waste
        record_waste(
            product=self.product,
            quantity=Decimal('2.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.user,
        )

        waste1.refresh_from_db()
        self.assertEqual(waste1.quantity_wasted, original_quantity)
        self.assertEqual(waste1.recorded_at, original_recorded_at)


class AtomicityTests(TransactionTestCase):
    """Tests for transaction atomicity - if one part fails, everything rolls back."""

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
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

    def test_atomicity_waste_record_failure_rolls_back_movement(self):
        """If WasteRecord creation fails, StockMovement is rolled back too."""
        initial_stock = self.product.stock_quantity
        initial_movement_count = StockMovement.objects.count()
        initial_waste_count = WasteRecord.objects.count()

        # Patch WasteRecord.objects.create to raise an error
        with patch('waste.services.WasteRecord.objects.create') as mock_create:
            mock_create.side_effect = IntegrityError('Simulated failure')

            with self.assertRaises(IntegrityError):
                record_waste(
                    product=self.product,
                    quantity=Decimal('1.0000'),
                    unit=self.kg_unit,
                    waste_category='Other',
                    user=self.user,
                )

        # No orphan movement - everything rolled back
        self.assertEqual(StockMovement.objects.count(), initial_movement_count)
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_atomicity_stock_update_failure_rolls_back(self):
        """If stock update fails, no records are created."""
        initial_stock = self.product.stock_quantity
        initial_movement_count = StockMovement.objects.count()
        initial_waste_count = WasteRecord.objects.count()

        # Patch product.save to raise an error
        with patch.object(Product, 'save') as mock_save:
            mock_save.side_effect = IntegrityError('Simulated failure')

            with self.assertRaises(IntegrityError):
                record_waste(
                    product=self.product,
                    quantity=Decimal('1.0000'),
                    unit=self.kg_unit,
                    waste_category='Other',
                    user=self.user,
                )

        # Everything rolled back
        self.assertEqual(StockMovement.objects.count(), initial_movement_count)
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count)


class FormValidationTests(TestCase):
    """Tests for WasteRecordForm validation."""

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

    def test_waste_category_required(self):
        """waste_category is required."""
        form = WasteRecordForm(data={
            'product': self.product.pk,
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'waste_category': '',
            'notes': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('waste_category', form.errors)

    def test_valid_form_accepted(self):
        """Valid form data is accepted."""
        form = WasteRecordForm(data={
            'product': self.product.pk,
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'waste_category': 'Product expired',
            'notes': '',
        })
        self.assertTrue(form.is_valid())

    def test_positive_quantity_required(self):
        """Quantity must be positive."""
        form = WasteRecordForm(data={
            'product': self.product.pk,
            'quantity': '0',
            'unit': self.kg_unit.pk,
            'waste_category': 'Other',
            'notes': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

    def test_unit_type_mismatch_rejected(self):
        """Form rejects unit type mismatch."""
        form = WasteRecordForm(data={
            'product': self.product.pk,
            'quantity': '1.0000',
            'unit': self.litre_unit.pk,
            'waste_category': 'Other',
            'notes': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Unit type mismatch', str(form.errors))

    def test_notes_max_length_enforced(self):
        """Notes field max length is enforced."""
        form = WasteRecordForm(data={
            'product': self.product.pk,
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'waste_category': 'Other',
            'notes': 'x' * 201,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('notes', form.errors)


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
        self.url = reverse('waste:record_waste')

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
        """Successful POST redirects and creates waste record."""
        self.client.login(username='staffuser', password='testpass123')
        initial_waste_count = WasteRecord.objects.count()
        initial_movement_count = StockMovement.objects.count()
        initial_stock = self.product.stock_quantity

        response = self.client.post(self.url, {
            'product': self.product.pk,
            'quantity': '2.0000',
            'unit': self.kg_unit.pk,
            'waste_category': 'Product expired',
            'notes': '',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count + 1)
        self.assertEqual(StockMovement.objects.count(), initial_movement_count + 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('2.0000'))

    def test_failed_post_shows_error_no_mutation(self):
        """Failed POST shows error and does not mutate stock."""
        self.client.login(username='staffuser', password='testpass123')
        initial_waste_count = WasteRecord.objects.count()
        initial_movement_count = StockMovement.objects.count()
        initial_stock = self.product.stock_quantity

        response = self.client.post(self.url, {
            'product': self.product.pk,
            'quantity': '100.0000',  # More than available
            'unit': self.kg_unit.pk,
            'waste_category': 'Other',
            'notes': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Insufficient stock')
        self.assertEqual(WasteRecord.objects.count(), initial_waste_count)
        self.assertEqual(StockMovement.objects.count(), initial_movement_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_waste_without_category_shows_error(self):
        """Waste without category shows form error."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'quantity': '1.0000',
            'unit': self.kg_unit.pk,
            'waste_category': '',
            'notes': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'required')


class WasteRecordModelTests(TestCase):
    """Tests for WasteRecord model."""

    def test_waste_category_choices_from_stock_movement(self):
        """WasteRecord.WASTE_CATEGORY_CHOICES comes from StockMovement."""
        self.assertEqual(
            WasteRecord.WASTE_CATEGORY_CHOICES,
            StockMovement.REASON_CATEGORY_CHOICES
        )
