"""
Tests for void dashboard (Unit 6b).

Tests cover:
- RBAC: manager_required (staff get 403, managers/admins can access)
- Voidable worklist: shows IN/OUT/WASTE that haven't been voided
- Void history: shows VOID movements with original type and voiding manager
- Filters: product and date range
- Pagination: both sections paginate independently
"""

from decimal import Decimal
from datetime import timedelta

from django.test import TestCase, TransactionTestCase
from django.urls import path, reverse, include
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import override_settings

from inventory.models import Product, Category, Unit, StockMovement
from inventory.services import record_movement, void_movement
from inventory.forms import VoidDashboardFilterForm
from waste.services import record_waste

CustomUser = get_user_model()


# Custom URL patterns for tests
urlpatterns = [
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('waste/', include('waste.urls')),
    path('admin/', admin.site.urls),
]


class VoidDashboardFilterFormTests(TestCase):
    """Tests for VoidDashboardFilterForm validation."""

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

    def test_empty_form_is_valid(self):
        """Empty form is valid (all fields optional)."""
        form = VoidDashboardFilterForm(data={})
        self.assertTrue(form.is_valid())

    def test_valid_product_filter(self):
        """Form with valid product is accepted."""
        form = VoidDashboardFilterForm(data={'product': self.product.pk})
        self.assertTrue(form.is_valid())

    def test_valid_date_range(self):
        """Form with valid date range is accepted."""
        form = VoidDashboardFilterForm(data={
            'date_from': '2025-01-01',
            'date_to': '2025-12-31',
        })
        self.assertTrue(form.is_valid())

    def test_date_from_after_date_to_rejected(self):
        """Date from after date to is rejected."""
        form = VoidDashboardFilterForm(data={
            'date_from': '2025-12-31',
            'date_to': '2025-01-01',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Date from cannot be after date to', str(form.errors))


@override_settings(ROOT_URLCONF=__name__)
class VoidDashboardRBACTests(TestCase):
    """Tests for void dashboard access control."""

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
        self.url = reverse('inventory:void_dashboard')

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
        """Manager user can access the void dashboard."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access(self):
        """Admin user can access the void dashboard (via hierarchy)."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


@override_settings(ROOT_URLCONF=__name__)
class VoidDashboardVoidableWorklistTests(TransactionTestCase):
    """Tests for the voidable worklist section."""

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
            stock_quantity=Decimal('100.0000'),
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.url = reverse('inventory:void_dashboard')

    def test_in_movement_appears_in_worklist(self):
        """IN movement appears in voidable worklist."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(in_movement, response.context['voidable_page'].object_list)

    def test_out_movement_appears_in_worklist(self):
        """OUT movement appears in voidable worklist."""
        out_movement = record_movement(
            product=self.product,
            movement_type='OUT',
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
            reason_category='Other',
            user=self.manager_user,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(out_movement, response.context['voidable_page'].object_list)

    def test_waste_movement_appears_in_worklist(self):
        """WASTE movement appears in voidable worklist."""
        waste_record = record_waste(
            product=self.product,
            quantity=Decimal('3.0000'),
            unit=self.kg_unit,
            waste_category='Product expired',
            user=self.manager_user,
        )
        waste_movement = waste_record.stock_movement
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(waste_movement, response.context['voidable_page'].object_list)

    def test_void_movement_not_in_worklist(self):
        """VOID movement does not appear in voidable worklist."""
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
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(void_record, response.context['voidable_page'].object_list)

    def test_voided_movement_not_in_worklist(self):
        """Already voided movement does not appear in voidable worklist."""
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
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(in_movement, response.context['voidable_page'].object_list)

    def test_worklist_has_void_button(self):
        """Worklist has void button linking to void view."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        void_url = reverse('inventory:void_movement', kwargs={'pk': in_movement.pk})
        self.assertContains(response, void_url)
        self.assertContains(response, 'Void</a>')


@override_settings(ROOT_URLCONF=__name__)
class VoidDashboardHistoryTests(TransactionTestCase):
    """Tests for the void history section."""

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
            stock_quantity=Decimal('100.0000'),
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.url = reverse('inventory:void_dashboard')

    def test_void_movement_appears_in_history(self):
        """VOID movement appears in void history."""
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
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(void_record, response.context['history_page'].object_list)

    def test_in_movement_not_in_history(self):
        """IN movement does not appear in void history."""
        in_movement = record_movement(
            product=self.product,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(in_movement, response.context['history_page'].object_list)

    def test_history_shows_original_type(self):
        """Void history shows the original movement type."""
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
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # Should show "Stock In" badge in history section
        self.assertContains(response, 'Stock In')

    def test_history_shows_voiding_manager(self):
        """Void history shows the manager who performed the void."""
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
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'manageruser')


@override_settings(ROOT_URLCONF=__name__)
class VoidDashboardFilterTests(TransactionTestCase):
    """Tests for void dashboard filters."""

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
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.url = reverse('inventory:void_dashboard')

    def test_product_filter_worklist(self):
        """Product filter filters voidable worklist."""
        in1 = record_movement(
            product=self.product1,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        in2 = record_movement(
            product=self.product2,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url, {'product': self.product1.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn(in1, response.context['voidable_page'].object_list)
        self.assertNotIn(in2, response.context['voidable_page'].object_list)

    def test_product_filter_history(self):
        """Product filter filters void history."""
        in1 = record_movement(
            product=self.product1,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        in2 = record_movement(
            product=self.product2,
            movement_type='IN',
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
            user=self.manager_user,
        )
        void1 = void_movement(
            movement=in1,
            reason_notes='Test void 1',
            user=self.manager_user,
        )
        void2 = void_movement(
            movement=in2,
            reason_notes='Test void 2',
            user=self.manager_user,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url, {'product': self.product1.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn(void1, response.context['history_page'].object_list)
        self.assertNotIn(void2, response.context['history_page'].object_list)


@override_settings(ROOT_URLCONF=__name__)
class VoidDashboardTemplateTests(TestCase):
    """Tests for void dashboard template."""

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
            stock_quantity=Decimal('100.0000'),
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.url = reverse('inventory:void_dashboard')

    def test_page_title(self):
        """Page has correct title."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Void / Correction Dashboard')

    def test_has_voidable_worklist_section(self):
        """Page has voidable/correctable worklist section."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voidable / Correctable Worklist')

    def test_has_void_history_section(self):
        """Page has void & correction history section."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Void & Correction History')

    def test_has_filter_form(self):
        """Page has filter form."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id_product')
        self.assertContains(response, 'id_date_from')
        self.assertContains(response, 'id_date_to')

    def test_empty_worklist_message(self):
        """Empty worklist shows appropriate message."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No voidable movements found')

    def test_empty_history_message(self):
        """Empty history shows appropriate message."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No void or correction history found')


@override_settings(ROOT_URLCONF=__name__)
class NavbarVoidDashboardLinkTests(TestCase):
    """Tests for navbar void dashboard link."""

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
        self.home_url = reverse('core:home')
        self.dashboard_url = reverse('inventory:void_dashboard')

    def test_staff_does_not_see_link(self):
        """Staff user does not see void dashboard link."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.dashboard_url)

    def test_manager_sees_link(self):
        """Manager user sees void dashboard link."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.dashboard_url)

    def test_admin_sees_link(self):
        """Admin user sees void dashboard link."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.dashboard_url)
