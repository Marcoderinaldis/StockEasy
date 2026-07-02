"""
Tests for waste recording and valued wastage analytics (Unit 5 + F13).

Tests cover:
- Service layer: record_waste, unit conversion, insufficient stock, atomic transactions
- Valued waste analytics: valued_waste_by, valued_waste_summary, k-anonymity
- View/RBAC: staff_required decorator, manager_required for analytics
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
    valued_waste_by,
    valued_waste_summary,
    K_ANON_MIN,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
)
from waste.forms import WasteRecordForm, ValuedWasteFilterForm
from inventory.models import PurchasePrice

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


# ---------------------------------------------------------------------------
# Valued Wastage Analytics Tests (F13)
# ---------------------------------------------------------------------------

class ValuedWasteByTests(TransactionTestCase):
    """Tests for valued_waste_by service function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product1 = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        self.product2 = Product.objects.create(
            name='Onions',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        # Create prices so movements will be valued
        PurchasePrice.objects.create(
            product=self.product1,
            unit_price=Decimal('2.50'),
            currency='GBP',
        )
        PurchasePrice.objects.create(
            product=self.product2,
            unit_price=Decimal('1.00'),
            currency='GBP',
        )
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

    def test_valued_total_equals_quantity_times_snapshot(self):
        """Valued £ = quantity × unit_cost_snapshot for known set."""
        # Record 3 waste events (k-anon threshold) for product1
        for _ in range(3):
            record_waste(
                product=self.product1,
                quantity=Decimal('2.0000'),  # 2kg
                unit=self.kg_unit,
                waste_category='Product expired',
                user=self.user,
            )
        # Expected: 3 events × 2kg × £2.50 = £15.00
        rows = valued_waste_by('product')
        tomatoes_row = next(r for r in rows if r['product_name'] == 'Tomatoes')
        self.assertEqual(tomatoes_row['valued_total'], Decimal('15.00'))
        self.assertEqual(tomatoes_row['event_count'], 3)
        self.assertEqual(tomatoes_row['total_qty'], Decimal('6.0000'))

    def test_null_snapshot_excluded_from_valued(self):
        """Rows with NULL unit_cost_snapshot are excluded from valued totals."""
        # Create a product with no price
        product_no_price = Product.objects.create(
            name='NoPrice',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        # Record 3 waste events (no price -> null snapshot)
        for _ in range(3):
            record_waste(
                product=product_no_price,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )
        # Should NOT appear in valued output
        rows = valued_waste_by('product')
        product_names = [r['product_name'] for r in rows]
        self.assertNotIn('NoPrice', product_names)

    def test_k_anon_suppresses_small_cells(self):
        """Category with only 2 events is suppressed into 'Suppressed' bucket."""
        # Record 2 events (below K_ANON_MIN=3) for product1
        for _ in range(2):
            record_waste(
                product=self.product1,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Delivery damaged',
                user=self.user,
            )
        # Record 5 events for product2 (passes threshold)
        for _ in range(5):
            record_waste(
                product=self.product2,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

        rows = valued_waste_by('product')
        product_names = [r['product_name'] for r in rows]

        # Tomatoes should be suppressed (only 2 events)
        self.assertNotIn('Tomatoes', product_names)
        # Onions passes with 5 events
        self.assertIn('Onions', product_names)
        # 'Suppressed (fewer than N events)' bucket should exist
        suppressed = [r for r in rows if 'suppressed' in r['product_name'].lower()]
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0]['event_count'], 2)

    def test_k_anon_boundary_3_events_not_suppressed(self):
        """Category with exactly 3 events (k=3) is NOT suppressed."""
        # Record exactly 3 events
        for _ in range(3):
            record_waste(
                product=self.product1,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Spillage/accidental waste',
                user=self.user,
            )

        rows = valued_waste_by('product')
        product_names = [r['product_name'] for r in rows]
        self.assertIn('Tomatoes', product_names)
        suppressed = [r for r in rows if 'suppressed' in r.get('product_name', '').lower()]
        self.assertEqual(len(suppressed), 0)

    def test_grand_total_unchanged_after_suppression(self):
        """Suppressed rows merge into 'Other' so grand total reconciles."""
        # Record 2 events for product1 (suppressed) = £5.00
        for _ in range(2):
            record_waste(
                product=self.product1,
                quantity=Decimal('1.0000'),  # 2 × 1kg × £2.50 = £5
                unit=self.kg_unit,
                waste_category='Counting error',
                user=self.user,
            )
        # Record 4 events for product2 (passes) = £4.00
        for _ in range(4):
            record_waste(
                product=self.product2,
                quantity=Decimal('1.0000'),  # 4 × 1kg × £1.00 = £4
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

        rows = valued_waste_by('product')
        total_from_rows = sum(r['valued_total'] for r in rows)
        expected_total = Decimal('9.00')  # £5 + £4
        self.assertEqual(total_from_rows, expected_total)

    def test_dimension_recorded_by_raises_value_error(self):
        """valued_waste_by raises ValueError if dimension='recorded_by'."""
        with self.assertRaises(ValueError) as context:
            valued_waste_by('recorded_by')
        self.assertIn('recorded_by', str(context.exception).lower())
        self.assertIn('prohibited', str(context.exception).lower())

    def test_dimension_user_raises_value_error(self):
        """valued_waste_by raises ValueError for any user-related dimension."""
        with self.assertRaises(ValueError):
            valued_waste_by('user')

    def test_only_waste_movements_included(self):
        """Only movement_type='WASTE' rows are included (VOID excluded)."""
        # Record a waste then void it
        from inventory.services import void_movement
        manager = CustomUser.objects.create_user(
            username='manager',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        waste = record_waste(
            product=self.product1,
            quantity=Decimal('1.0000'),
            unit=self.kg_unit,
            waste_category='Other',
            user=self.user,
        )
        # Void the waste
        void_movement(
            movement=waste.stock_movement,
            reason_notes='Test void',
            user=manager,
        )
        # Record 2 more waste events
        for _ in range(2):
            record_waste(
                product=self.product1,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

        # Query - should see 3 WASTE movements total (including voided one),
        # but NOT the VOID movement itself
        rows = valued_waste_by('product')
        total_events = sum(r['event_count'] for r in rows)
        # 3 WASTE events (including the voided one - it's still a WASTE row)
        # The VOID movement is movement_type='VOID', not 'WASTE'
        self.assertEqual(total_events, 3)


class ValuedWasteSummaryTests(TransactionTestCase):
    """Tests for valued_waste_summary convenience function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product_with_price = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        self.product_no_price = Product.objects.create(
            name='NoPrice',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        PurchasePrice.objects.create(
            product=self.product_with_price,
            unit_price=Decimal('2.00'),
            currency='GBP',
        )
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

    def test_unvalued_count_surfaces_null_snapshots(self):
        """Unvalued waste (null snapshot) is reported separately."""
        # Record 3 valued waste events
        for _ in range(3):
            record_waste(
                product=self.product_with_price,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )
        # Record 2 unvalued waste events
        for _ in range(2):
            record_waste(
                product=self.product_no_price,
                quantity=Decimal('5.0000'),
                unit=self.kg_unit,
                waste_category='Product expired',
                user=self.user,
            )

        summary = valued_waste_summary()

        self.assertEqual(summary['valued_event_count'], 3)
        self.assertEqual(summary['valued_total_qty'], Decimal('3.0000'))
        self.assertEqual(summary['valued_total'], Decimal('6.00'))  # 3 × £2.00

        self.assertEqual(summary['unvalued_event_count'], 2)
        self.assertEqual(summary['unvalued_total_qty'], Decimal('10.0000'))

        self.assertEqual(summary['k_anon_min'], K_ANON_MIN)

    def test_summary_contains_by_product_and_by_category(self):
        """Summary includes both 'by_product' and 'by_category' breakdowns."""
        for _ in range(3):
            record_waste(
                product=self.product_with_price,
                quantity=Decimal('1.0000'),
                unit=self.kg_unit,
                waste_category='Other',
                user=self.user,
            )

        summary = valued_waste_summary()

        self.assertIn('by_product', summary)
        self.assertIn('by_category', summary)
        self.assertIsInstance(summary['by_product'], list)
        self.assertIsInstance(summary['by_category'], list)


class ValuedWasteAnalyticsViewTests(TestCase):
    """Tests for valued_waste_analytics view RBAC."""

    def setUp(self):
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
        self.url = reverse('waste:valued_waste_analytics')

    def test_staff_gets_403(self):
        """Staff user gets 403 Forbidden on analytics view."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_manager_gets_200(self):
        """Manager user can access analytics view."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_gets_200(self):
        """Admin user can access analytics view (via hierarchy)."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_k_anon_footnote_in_response(self):
        """Response includes k-anonymity disclosure."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertContains(response, 'fewer than')
        self.assertContains(response, 'merged')


class ValuedWasteFilterFormTests(TestCase):
    """Tests for ValuedWasteFilterForm."""

    def test_form_has_no_recorded_by_field(self):
        """Form has no recorded_by/user field by construction."""
        form = ValuedWasteFilterForm()
        field_names = list(form.fields.keys())
        self.assertNotIn('recorded_by', field_names)
        self.assertNotIn('user', field_names)
        self.assertNotIn('who', field_names)

    def test_valid_empty_form_accepted(self):
        """Empty form (no filters) is valid."""
        form = ValuedWasteFilterForm(data={})
        self.assertTrue(form.is_valid())

    def test_date_range_validation(self):
        """date_from after date_to is rejected."""
        form = ValuedWasteFilterForm(data={
            'date_from': '2025-06-15',
            'date_to': '2025-06-01',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Date from cannot be after date to', str(form.errors))
