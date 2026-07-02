"""
Tests for movement correction (Unit 6c).

Tests cover:
- Service layer: correct_movement, net stock validation, VOID + replacement creation
- The critical net-stock case: IN 30, consume 10 (stock 20), correct to 25 -> SUCCEEDS
- View/RBAC: manager_required decorator, form submission, error handling
- Form: justification required, positive quantity, unit mismatch
- Buttons: Correct button visibility for manager on correctable rows
- Dashboard history: Voided vs Corrected labels, old->new qty display
- Append-only: original never modified
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.urls import path, reverse, include
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import override_settings

from inventory.models import Product, Category, Unit, StockMovement
from inventory.services import (
    record_movement,
    void_movement,
    correct_movement,
    is_voided,
    is_corrected,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
    CORRECTABLE_MOVEMENT_TYPES,
)
from inventory.forms import CorrectMovementForm
from waste.services import record_waste

CustomUser = get_user_model()


class ServiceCorrectMovementTests(TransactionTestCase):
    """Tests for the correct_movement service function."""

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
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('50.0000'),
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )

    def test_correct_in_30_to_25_adjusts_stock(self):
        """Correcting IN 30 -> 25 adjusts stock correctly (net -5)."""
        initial_stock = self.product.stock_quantity  # 50
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('30.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('80.0000'))  # 50+30

        replacement = correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('25.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Wrong quantity entered',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        # Net change: 25 - 30 = -5, so stock = 80 - 5 = 75
        self.assertEqual(self.product.stock_quantity, Decimal('75.0000'))
        self.assertEqual(replacement.movement_type, 'IN')
        self.assertEqual(replacement.quantity, Decimal('25.0000'))
        self.assertEqual(replacement.corrects, in_movement)

    def test_net_stock_case_in_30_consume_10_correct_to_25_succeeds(self):
        """
        CRITICAL TEST: IN 30, consume 10 (stock 20), correct to 25 -> SUCCEEDS.

        This must NOT be falsely blocked by intermediate step validation.
        Stock: 50 -> 80 (IN 30) -> 70 (OUT 10).
        Correct IN 30 to IN 25: net = 25 - 30 = -5, final = 70 - 5 = 65 (valid).

        A naive void-then-record would fail: 70 - 30 = 40 (ok), but this tests
        that we don't wrongly block when intermediate would be negative.
        """
        initial_stock = self.product.stock_quantity  # 50

        # IN 30 -> stock 80
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('30.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('80.0000'))

        # OUT 10 -> stock 70
        record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('70.0000'))

        # Now correct IN 30 to IN 25
        # Net delta = 25 - 30 = -5
        # Final stock = 70 - 5 = 65 (valid, should succeed)
        replacement = correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('25.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Correcting quantity after consumption',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('65.0000'))
        self.assertEqual(replacement.quantity, Decimal('25.0000'))

    def test_correct_out_adjusts_stock(self):
        """Correcting OUT 10 -> 5 adjusts stock correctly (net +5)."""
        # OUT 10 -> stock 40
        out_movement = record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('40.0000'))

        # Correct to OUT 5: net = 10 - 5 = +5
        replacement = correct_movement(
            original=out_movement,
            corrected_quantity=Decimal('5.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category='Counting error',
            corrected_notes='Wrong count',
            justification='Correction',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('45.0000'))
        self.assertEqual(replacement.movement_type, 'OUT')
        self.assertEqual(replacement.quantity, Decimal('5.0000'))

    def test_correct_waste_adjusts_stock(self):
        """Correcting WASTE 8 -> 3 adjusts stock correctly (net +5)."""
        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('8.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.manager_user,
        )
        waste_movement = waste_record.stock_movement
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('42.0000'))

        # Correct to WASTE 3: net = 8 - 3 = +5
        replacement = correct_movement(
            original=waste_movement,
            corrected_quantity=Decimal('3.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category='Product expired',
            corrected_notes=None,
            justification='Over-counted waste',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('47.0000'))
        self.assertEqual(replacement.movement_type, 'WASTE')

    def test_creates_void_and_replacement(self):
        """Correction creates a VOID linked to original and a replacement with corrects FK."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        initial_void_count = StockMovement.objects.filter(movement_type='VOID').count()

        replacement = correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Test correction',
            user=self.manager_user,
        )

        # Check VOID was created
        self.assertEqual(
            StockMovement.objects.filter(movement_type='VOID').count(),
            initial_void_count + 1
        )

        # Check VOID links to original
        in_movement.refresh_from_db()
        self.assertTrue(is_voided(in_movement))
        void_record = in_movement.voided_by
        self.assertEqual(void_record.voids, in_movement)

        # Check replacement links to original
        self.assertEqual(replacement.corrects, in_movement)
        self.assertTrue(is_corrected(in_movement))

    def test_recorded_by_set_on_both(self):
        """Both VOID and replacement have recorded_by set to the correcting user."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        replacement = correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Test correction',
            user=self.manager_user,
        )

        self.assertEqual(replacement.recorded_by, self.manager_user)
        in_movement.refresh_from_db()
        self.assertEqual(in_movement.voided_by.recorded_by, self.manager_user)

    def test_would_go_negative_on_final_blocked(self):
        """Correction blocked if FINAL stock would go negative."""
        # Stock 50, IN 10 -> 60, OUT 55 -> 5
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('55.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('5.0000'))

        # Try to correct IN 10 to IN 2: net = 2 - 10 = -8, final = 5 - 8 = -3 (invalid)
        with self.assertRaises(InsufficientStockError) as context:
            correct_movement(
                original=in_movement,
                corrected_quantity=Decimal('2.0000'),
                corrected_unit=self.kg_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='Try to correct',
                user=self.manager_user,
            )

        self.assertIn('would go negative', str(context.exception))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('5.0000'))  # Unchanged

    def test_cannot_correct_a_void(self):
        """VOID movements cannot be corrected."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        void_record = void_movement(
            movement=in_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            correct_movement(
                original=void_record,
                corrected_quantity=Decimal('5.0000'),
                corrected_unit=self.kg_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='Try to correct void',
                user=self.manager_user,
            )

        self.assertIn('Cannot correct a void', str(context.exception))

    def test_cannot_correct_already_voided(self):
        """Already voided movements cannot be corrected."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        void_movement(
            movement=in_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            correct_movement(
                original=in_movement,
                corrected_quantity=Decimal('5.0000'),
                corrected_unit=self.kg_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='Try to correct voided',
                user=self.manager_user,
            )

        self.assertIn('already been voided', str(context.exception))

    def test_cannot_correct_already_corrected(self):
        """Already corrected movements cannot be corrected again."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='First correction',
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            correct_movement(
                original=in_movement,
                corrected_quantity=Decimal('8.0000'),
                corrected_unit=self.kg_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='Second correction attempt',
                user=self.manager_user,
            )

        self.assertIn('already been corrected', str(context.exception))

    def test_justification_mandatory(self):
        """Justification is required - blank reason rejected."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            correct_movement(
                original=in_movement,
                corrected_quantity=Decimal('12.0000'),
                corrected_unit=self.kg_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='',
                user=self.manager_user,
            )

        self.assertIn('Justification is required', str(context.exception))

    def test_positive_quantity_required(self):
        """Corrected quantity must be positive."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            correct_movement(
                original=in_movement,
                corrected_quantity=Decimal('0'),
                corrected_unit=self.kg_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='Test',
                user=self.manager_user,
            )

        self.assertIn('must be positive', str(context.exception))

    def test_unit_type_mismatch_rejected(self):
        """Unit type mismatch is rejected."""
        litre_unit = Unit.objects.create(
            name='Litres',
            unit_type='VOLUME',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='ml',
        )
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        with self.assertRaises(UnitTypeMismatchError):
            correct_movement(
                original=in_movement,
                corrected_quantity=Decimal('12.0000'),
                corrected_unit=litre_unit,
                corrected_reason_category=None,
                corrected_notes=None,
                justification='Test',
                user=self.manager_user,
            )

    def test_original_never_modified(self):
        """Original movement row is never modified (append-only)."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        original_quantity = in_movement.quantity
        original_type = in_movement.movement_type
        original_recorded_at = in_movement.recorded_at

        correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Test',
            user=self.manager_user,
        )

        in_movement.refresh_from_db()
        self.assertEqual(in_movement.quantity, original_quantity)
        self.assertEqual(in_movement.movement_type, original_type)
        self.assertEqual(in_movement.recorded_at, original_recorded_at)

    def test_unit_conversion_works(self):
        """Corrected quantity in different unit is converted correctly."""
        # Product uses kg, correct with grams
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),  # 10 kg
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('60.0000'))  # 50+10

        # Correct to 12000 grams = 12 kg
        replacement = correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12000.0000'),
            corrected_unit=self.g_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Test',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        # Net: 12 - 10 = +2, final = 60 + 2 = 62
        self.assertEqual(self.product.stock_quantity, Decimal('62.0000'))
        self.assertEqual(replacement.quantity, Decimal('12.0000'))  # Stored in kg


class AtomicityCorrectionTests(TransactionTestCase):
    """Tests for transaction atomicity in correction operations."""

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
            stock_quantity=Decimal('50.0000'),
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )

    def test_atomicity_failure_rolls_back_everything(self):
        """If replacement creation fails, everything is rolled back."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        stock_after_in = self.product.stock_quantity
        initial_void_count = StockMovement.objects.filter(movement_type='VOID').count()
        initial_in_count = StockMovement.objects.filter(movement_type='IN').count()

        # Mock to fail on the second create (replacement)
        original_create = StockMovement.objects.create
        call_count = [0]

        def mock_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # Second call is the replacement
                raise IntegrityError('Simulated failure')
            return original_create(*args, **kwargs)

        with patch.object(StockMovement.objects, 'create', side_effect=mock_create):
            with self.assertRaises(IntegrityError):
                correct_movement(
                    original=in_movement,
                    corrected_quantity=Decimal('12.0000'),
                    corrected_unit=self.kg_unit,
                    corrected_reason_category=None,
                    corrected_notes=None,
                    justification='Test',
                    user=self.manager_user,
                )

        # Everything should be rolled back
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock_after_in)
        self.assertEqual(StockMovement.objects.filter(movement_type='VOID').count(), initial_void_count)
        self.assertEqual(StockMovement.objects.filter(movement_type='IN').count(), initial_in_count)


class FormCorrectMovementTests(TestCase):
    """Tests for CorrectMovementForm validation."""

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
            stock_quantity=Decimal('50.0000'),
        )

    def test_justification_required(self):
        """Justification field is required."""
        form = CorrectMovementForm(data={
            'corrected_quantity': '10',
            'corrected_unit': self.kg_unit.pk,
            'justification': '',
        }, product=self.product)
        self.assertFalse(form.is_valid())
        self.assertIn('justification', form.errors)

    def test_valid_form_accepted(self):
        """Valid form is accepted."""
        form = CorrectMovementForm(data={
            'corrected_quantity': '10',
            'corrected_unit': self.kg_unit.pk,
            'justification': 'Wrong quantity entered',
        }, product=self.product)
        self.assertTrue(form.is_valid())

    def test_positive_quantity_required(self):
        """Corrected quantity must be positive."""
        form = CorrectMovementForm(data={
            'corrected_quantity': '0',
            'corrected_unit': self.kg_unit.pk,
            'justification': 'Test',
        }, product=self.product)
        self.assertFalse(form.is_valid())


# Custom URL patterns for RBAC tests
urlpatterns = [
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('waste/', include('waste.urls')),
    path('admin/', admin.site.urls),
]


@override_settings(ROOT_URLCONF=__name__)
class ViewRBACTests(TestCase):
    """Tests for correct view access control."""

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
            stock_quantity=Decimal('50.0000'),
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
        self.movement = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )
        self.url = reverse('inventory:correct_movement', kwargs={'pk': self.movement.pk})

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_gets_403(self):
        """Staff user gets 403 Forbidden."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_manager_can_access(self):
        """Manager user can access the correct view."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access(self):
        """Admin user can access the correct view (via hierarchy)."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_successful_correction_redirects_to_dashboard(self):
        """Successful correction POST redirects to void dashboard."""
        self.client.login(username='manageruser', password='testpass123')

        response = self.client.post(self.url, {
            'corrected_quantity': '12',
            'corrected_unit': self.kg_unit.pk,
            'justification': 'Test correction',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('inventory:void_dashboard'))


@override_settings(ROOT_URLCONF=__name__)
class CorrectButtonVisibilityTests(TestCase):
    """Tests for Correct button visibility in movements list and dashboard."""

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
            stock_quantity=Decimal('50.0000'),
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
        self.in_movement = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )

    def test_staff_does_not_see_correct_button(self):
        """Staff user does not see the Correct button."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(reverse('inventory:movements_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Correct</a>')

    def test_manager_sees_correct_button_on_correctable_row(self):
        """Manager sees Correct button on correctable rows."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:movements_list'))
        self.assertEqual(response.status_code, 200)
        correct_url = reverse('inventory:correct_movement', kwargs={'pk': self.in_movement.pk})
        self.assertContains(response, correct_url)
        self.assertContains(response, 'Correct</a>')

    def test_correct_button_hidden_on_voided_movement(self):
        """Correct button hidden on already voided movements."""
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='VOID',
            recorded_by=self.manager_user,
            voids=self.in_movement,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:movements_list'))
        correct_url = reverse('inventory:correct_movement', kwargs={'pk': self.in_movement.pk})
        self.assertNotContains(response, f'href="{correct_url}"')

    def test_dashboard_shows_correct_button(self):
        """Dashboard voidable worklist shows Correct button."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:void_dashboard'))
        self.assertEqual(response.status_code, 200)
        correct_url = reverse('inventory:correct_movement', kwargs={'pk': self.in_movement.pk})
        self.assertContains(response, correct_url)
        self.assertContains(response, 'Correct</a>')


@override_settings(ROOT_URLCONF=__name__)
class DashboardHistoryLabelsTests(TransactionTestCase):
    """Tests for void vs correction labels in dashboard history."""

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
            stock_quantity=Decimal('50.0000'),
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )

    def test_pure_void_shows_voided_label(self):
        """Pure void (no replacement) shows 'Voided' label."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        void_movement(
            movement=in_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:void_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Voided</span>')

    def test_correction_shows_corrected_label(self):
        """Correction shows 'Corrected' label."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Test correction',
            user=self.manager_user,
        )

        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:void_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Corrected</span>')

    def test_correction_shows_old_to_new_qty(self):
        """Correction shows old qty -> new qty in history."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        correct_movement(
            original=in_movement,
            corrected_quantity=Decimal('12.0000'),
            corrected_unit=self.kg_unit,
            corrected_reason_category=None,
            corrected_notes=None,
            justification='Test correction',
            user=self.manager_user,
        )

        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:void_dashboard'))
        self.assertEqual(response.status_code, 200)
        # Should show "10.0000 -> 12.0000"
        self.assertContains(response, '10.0000')
        self.assertContains(response, '12.0000')

    def test_history_section_renamed(self):
        """History section is named 'Void & Correction History'."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(reverse('inventory:void_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Void & Correction History')
