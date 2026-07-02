"""
Tests for void movement (Unit 6).

Tests cover:
- Service layer: void_movement, stock reversal, double-void prevention, atomicity
- View/RBAC: manager_required decorator, form submission, error handling
- Form: justification required
- Movements list: Actions column visibility, Void button on voidable rows
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.urls import path, reverse, include
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from inventory.models import Product, Category, Unit, StockMovement
from inventory.services import (
    record_movement,
    void_movement,
    is_voided,
    StockValidationError,
    InsufficientStockError,
    VOIDABLE_MOVEMENT_TYPES,
)
from inventory.forms import VoidMovementForm
from waste.services import record_waste

CustomUser = get_user_model()


class ServiceVoidMovementTests(TransactionTestCase):
    """Tests for the void_movement service function."""

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

    def test_void_in_subtracts_quantity(self):
        """Voiding an IN movement subtracts the quantity back from stock."""
        initial_stock = self.product.stock_quantity
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock + Decimal('10.0000'))

        void_record = void_movement(
            movement=in_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)
        self.assertEqual(void_record.movement_type, 'VOID')
        self.assertEqual(void_record.quantity, Decimal('10.0000'))

    def test_void_out_adds_quantity(self):
        """Voiding an OUT movement adds the quantity back to stock."""
        initial_stock = self.product.stock_quantity
        out_movement = record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('5.0000'))

        void_record = void_movement(
            movement=out_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)
        self.assertEqual(void_record.movement_type, 'VOID')

    def test_void_waste_adds_quantity(self):
        """Voiding a WASTE movement adds the quantity back to stock."""
        initial_stock = self.product.stock_quantity
        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('3.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.manager_user,
        )
        waste_movement = waste_record.stock_movement
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('3.0000'))

        void_record = void_movement(
            movement=waste_movement,
            reason_notes='Test void waste',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)
        self.assertEqual(void_record.movement_type, 'VOID')

    def test_void_creates_linked_movement(self):
        """Voiding creates a VOID StockMovement linked via voids FK."""
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

        self.assertEqual(void_record.voids, in_movement)
        self.assertEqual(void_record.voids_id, in_movement.pk)
        # Reverse accessor
        in_movement.refresh_from_db()
        self.assertEqual(in_movement.voided_by, void_record)

    def test_void_recorded_by_set(self):
        """VOID movement has recorded_by set to the user who voided."""
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

        self.assertEqual(void_record.recorded_by, self.manager_user)

    def test_double_void_blocked_service_check(self):
        """Second void on same movement is rejected at service level."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        void_movement(
            movement=in_movement,
            reason_notes='First void',
            user=self.manager_user,
        )

        self.product.refresh_from_db()
        stock_after_first_void = self.product.stock_quantity
        void_count = StockMovement.objects.filter(movement_type='VOID').count()

        with self.assertRaises(StockValidationError) as context:
            void_movement(
                movement=in_movement,
                reason_notes='Second void attempt',
                user=self.manager_user,
            )

        self.assertIn('already been voided', str(context.exception))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock_after_first_void)
        self.assertEqual(StockMovement.objects.filter(movement_type='VOID').count(), void_count)

    def test_double_void_blocked_db_constraint(self):
        """OneToOne constraint prevents double void at DB level."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        void_movement(
            movement=in_movement,
            reason_notes='First void',
            user=self.manager_user,
        )

        # Try to bypass service and create directly (simulates race condition)
        with self.assertRaises(IntegrityError):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('10.0000'),
                movement_type='VOID',
                reason_notes='Bypass attempt',
                recorded_by=self.manager_user,
                voids=in_movement,  # This violates OneToOne
            )

    def test_cannot_void_a_void(self):
        """VOID movements cannot be voided."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        void_record = void_movement(
            movement=in_movement,
            reason_notes='First void',
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            void_movement(
                movement=void_record,
                reason_notes='Attempt to void a void',
                user=self.manager_user,
            )

        self.assertIn('Cannot void a void', str(context.exception))

    def test_cannot_void_adjustment_types(self):
        """ADJUSTMENT_IN and ADJUSTMENT_OUT cannot be voided."""
        # Create an adjustment movement directly (bypassing service)
        adjustment = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('5.0000'),
            movement_type='ADJUSTMENT_IN',
            recorded_by=self.manager_user,
        )

        with self.assertRaises(StockValidationError) as context:
            void_movement(
                movement=adjustment,
                reason_notes='Attempt to void adjustment',
                user=self.manager_user,
            )

        self.assertIn('cannot be voided', str(context.exception))

    def test_justification_mandatory(self):
        """Justification is required - blank reason rejected."""
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

        with self.assertRaises(StockValidationError) as context:
            void_movement(
                movement=in_movement,
                reason_notes='',
                user=self.manager_user,
            )

        self.assertIn('Justification is required', str(context.exception))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock_after_in)  # Unchanged
        self.assertEqual(StockMovement.objects.filter(movement_type='VOID').count(), initial_void_count)

    def test_justification_mandatory_whitespace_only(self):
        """Justification with only whitespace is rejected."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        with self.assertRaises(StockValidationError):
            void_movement(
                movement=in_movement,
                reason_notes='   ',
                user=self.manager_user,
            )

    def test_would_go_negative_blocked(self):
        """Voiding an IN when stock has been consumed is blocked."""
        # Start with 50, add 30, remove 25 -> stock = 55
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('30.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('80.0000'))

        record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('25.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('55.0000'))

        # Now try to void the IN of 30 - would make stock 25 (55-30=25), but we need to check
        # Actually 55 - 30 = 25 which is positive, so this should work
        # Let me create a better test case: stock=50, IN 30 -> 80, OUT 70 -> 10
        # Then void the IN 30 -> 10-30 = -20 (negative, blocked)

        # Reset scenario
        self.product.stock_quantity = Decimal('50.0000')
        self.product.save()

        in_movement2 = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('30.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('80.0000'))

        record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('70.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('10.0000'))

        initial_void_count = StockMovement.objects.filter(movement_type='VOID').count()

        with self.assertRaises(InsufficientStockError) as context:
            void_movement(
                movement=in_movement2,
                reason_notes='Trying to void consumed stock',
                user=self.manager_user,
            )

        self.assertIn('would go negative', str(context.exception))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('10.0000'))  # Unchanged
        self.assertEqual(StockMovement.objects.filter(movement_type='VOID').count(), initial_void_count)

    def test_original_row_never_modified(self):
        """Original movement row is never modified by void (append-only)."""
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

        void_movement(
            movement=in_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        in_movement.refresh_from_db()
        self.assertEqual(in_movement.quantity, original_quantity)
        self.assertEqual(in_movement.movement_type, original_type)
        self.assertEqual(in_movement.recorded_at, original_recorded_at)

    def test_is_voided_helper(self):
        """is_voided helper correctly identifies voided movements."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )

        self.assertFalse(is_voided(in_movement))

        void_movement(
            movement=in_movement,
            reason_notes='Test void',
            user=self.manager_user,
        )

        in_movement.refresh_from_db()
        self.assertTrue(is_voided(in_movement))


class AtomicityVoidTests(TransactionTestCase):
    """Tests for transaction atomicity in void operations."""

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

    def test_atomicity_void_creation_failure_rolls_back_stock(self):
        """If VOID creation fails, stock change is rolled back."""
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

        with patch('inventory.services.StockMovement.objects.create') as mock_create:
            mock_create.side_effect = IntegrityError('Simulated failure')

            with self.assertRaises(IntegrityError):
                void_movement(
                    movement=in_movement,
                    reason_notes='Test void',
                    user=self.manager_user,
                )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock_after_in)  # Unchanged
        self.assertEqual(StockMovement.objects.filter(movement_type='VOID').count(), initial_void_count)


class FormVoidMovementTests(TestCase):
    """Tests for VoidMovementForm validation."""

    def test_justification_required(self):
        """Justification field is required."""
        form = VoidMovementForm(data={'justification': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('justification', form.errors)

    def test_valid_justification_accepted(self):
        """Valid justification is accepted."""
        form = VoidMovementForm(data={'justification': 'This was entered incorrectly'})
        self.assertTrue(form.is_valid())

    def test_whitespace_only_rejected(self):
        """Whitespace-only justification is rejected."""
        form = VoidMovementForm(data={'justification': '   '})
        self.assertFalse(form.is_valid())


# Custom URL patterns for RBAC tests
urlpatterns = [
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('waste/', include('waste.urls')),
    path('costing/', include('costing.urls')),
    path('admin/', admin.site.urls),
]


from django.test import override_settings


@override_settings(ROOT_URLCONF=__name__)
class ViewRBACTests(TestCase):
    """Tests for void view access control."""

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
        self.url = reverse('inventory:void_movement', kwargs={'pk': self.movement.pk})

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
        """Manager user can access the void view."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access(self):
        """Admin user can access the void view (via hierarchy)."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_successful_void_redirects(self):
        """Successful void POST redirects to movements list."""
        self.client.login(username='manageruser', password='testpass123')
        initial_stock = self.product.stock_quantity

        response = self.client.post(self.url, {
            'justification': 'Test void justification',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('inventory:movements_list'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock - Decimal('10.0000'))

    def test_void_without_justification_shows_error(self):
        """POST without justification shows form error."""
        self.client.login(username='manageruser', password='testpass123')
        initial_stock = self.product.stock_quantity

        response = self.client.post(self.url, {
            'justification': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'required')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)


@override_settings(ROOT_URLCONF=__name__)
class MovementsListActionsTests(TestCase):
    """Tests for the Actions column in movements list."""

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
        self.in_movement = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )
        self.url = reverse('inventory:movements_list')

    def test_staff_does_not_see_actions_column(self):
        """Staff user does not see the Actions column."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '>Actions</th>')
        self.assertFalse(response.context['show_actions'])

    def test_manager_sees_actions_column(self):
        """Manager user sees the Actions column."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Actions</th>')
        self.assertTrue(response.context['show_actions'])

    def test_admin_sees_actions_column(self):
        """Admin user sees the Actions column."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Actions</th>')
        self.assertTrue(response.context['show_actions'])

    def test_void_button_shows_on_voidable_rows(self):
        """Void button appears on IN/OUT/WASTE movements that aren't voided."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Void</a>')
        void_url = reverse('inventory:void_movement', kwargs={'pk': self.in_movement.pk})
        self.assertContains(response, void_url)

    def test_void_button_hidden_on_void_movements(self):
        """Void button does not appear on VOID movements."""
        void_movement = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='VOID',
            recorded_by=self.manager_user,
            voids=self.in_movement,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        void_url = reverse('inventory:void_movement', kwargs={'pk': void_movement.pk})
        self.assertNotContains(response, f'href="{void_url}"')

    def test_voided_movement_marked(self):
        """Voided movements show a 'Voided' badge."""
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='VOID',
            recorded_by=self.manager_user,
            voids=self.in_movement,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voided</span>')

    def test_void_button_hidden_on_already_voided(self):
        """Void button does not appear on movements that have been voided."""
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('10.0000'),
            movement_type='VOID',
            recorded_by=self.manager_user,
            voids=self.in_movement,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        void_url = reverse('inventory:void_movement', kwargs={'pk': self.in_movement.pk})
        self.assertNotContains(response, f'href="{void_url}"')
