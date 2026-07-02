"""
Tests for movements list view (Unit 4).

Tests cover:
- RBAC: staff, manager, admin access; anonymous redirect
- Filters: product, movement_type, date range, combined filters
- Pagination
- Recorder column visibility (manager/admin only, not staff)
- No user/recorded_by filter parameter allowed
- Read-only: no writes to ledger
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import path, reverse, include
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory.models import Product, Category, Unit, StockMovement
from inventory.forms import MovementFilterForm

CustomUser = get_user_model()


urlpatterns = [
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('waste/', include('waste.urls')),
    path('costing/', include('costing.urls')),
    path('admin/', admin.site.urls),
]


@override_settings(ROOT_URLCONF=__name__)
class MovementsListRBACTests(TestCase):
    """Tests for movements list access control."""

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
        self.url = reverse('inventory:movements_list')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_can_access(self):
        """Staff user can access the movements list."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_manager_can_access(self):
        """Manager user can access the movements list."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access(self):
        """Admin user can access the movements list."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


@override_settings(ROOT_URLCONF=__name__)
class RecorderColumnVisibilityTests(TestCase):
    """Tests for recorder column visibility based on role."""

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
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('5.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )
        self.url = reverse('inventory:movements_list')

    def test_staff_does_not_see_recorder_column(self):
        """Staff user does not see the 'Recorded by' column."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Recorded by')
        self.assertFalse(response.context['show_recorder_column'])

    def test_manager_sees_recorder_column(self):
        """Manager user sees the 'Recorded by' column."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recorded by')
        self.assertTrue(response.context['show_recorder_column'])

    def test_admin_sees_recorder_column(self):
        """Admin user sees the 'Recorded by' column."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recorded by')
        self.assertTrue(response.context['show_recorder_column'])


@override_settings(ROOT_URLCONF=__name__)
class MovementsListFilterTests(TestCase):
    """Tests for movements list filtering."""

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
        self.product1 = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.product2 = Product.objects.create(
            name='Milk',
            category=self.category,
            unit=self.litre_unit,
            stock_quantity=Decimal('5.0000'),
        )
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )

        self.movement1 = StockMovement.objects.create(
            product=self.product1,
            quantity=Decimal('5.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )
        self.movement2 = StockMovement.objects.create(
            product=self.product1,
            quantity=Decimal('2.0000'),
            movement_type='OUT',
            reason_category='Other',
            recorded_by=self.staff_user,
        )
        self.movement3 = StockMovement.objects.create(
            product=self.product2,
            quantity=Decimal('3.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )

        self.url = reverse('inventory:movements_list')

    def test_no_filters_shows_all(self):
        """No filters shows all movements."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 3)

    def test_filter_by_product(self):
        """Filter by product narrows results."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url, {'product': self.product1.pk})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 2)
        for m in movements:
            self.assertEqual(m.product, self.product1)

    def test_filter_by_movement_type_in(self):
        """Filter by movement_type IN narrows results."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url, {'movement_type': 'IN'})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 2)
        for m in movements:
            self.assertEqual(m.movement_type, 'IN')

    def test_filter_by_movement_type_out(self):
        """Filter by movement_type OUT narrows results."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url, {'movement_type': 'OUT'})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].movement_type, 'OUT')

    def test_filter_by_date_from(self):
        """Filter by date_from narrows results."""
        self.client.login(username='staffuser', password='testpass123')
        today = date.today()
        response = self.client.get(self.url, {'date_from': today.isoformat()})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 3)

    def test_filter_by_date_to(self):
        """Filter by date_to narrows results."""
        self.client.login(username='staffuser', password='testpass123')
        yesterday = date.today() - timedelta(days=1)
        response = self.client.get(self.url, {'date_to': yesterday.isoformat()})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 0)

    def test_combined_filters(self):
        """Multiple filters combined narrow results correctly."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url, {
            'product': self.product1.pk,
            'movement_type': 'IN',
        })
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].product, self.product1)
        self.assertEqual(movements[0].movement_type, 'IN')


@override_settings(ROOT_URLCONF=__name__)
class NoUserFilterTests(TestCase):
    """Tests that user/recorded_by filter is not allowed."""

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
        self.staff_user1 = CustomUser.objects.create_user(
            username='staffuser1',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.staff_user2 = CustomUser.objects.create_user(
            username='staffuser2',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('5.0000'),
            movement_type='IN',
            recorded_by=self.staff_user1,
        )
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('3.0000'),
            movement_type='IN',
            recorded_by=self.staff_user2,
        )
        self.url = reverse('inventory:movements_list')

    def test_user_filter_param_ignored(self):
        """A user/recorded_by filter parameter in querystring is ignored."""
        self.client.login(username='staffuser1', password='testpass123')
        response = self.client.get(self.url, {'recorded_by': self.staff_user1.pk})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 2)

    def test_created_by_filter_param_ignored(self):
        """A created_by filter parameter in querystring is ignored."""
        self.client.login(username='staffuser1', password='testpass123')
        response = self.client.get(self.url, {'created_by': self.staff_user1.pk})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 2)

    def test_user_filter_param_ignored_even_for_manager(self):
        """Manager cannot filter by user either."""
        manager = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url, {'recorded_by': self.staff_user1.pk})
        self.assertEqual(response.status_code, 200)
        movements = list(response.context['page_obj'])
        self.assertEqual(len(movements), 2)


@override_settings(ROOT_URLCONF=__name__)
class PaginationTests(TestCase):
    """Tests for movements list pagination."""

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
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        for i in range(30):
            StockMovement.objects.create(
                product=self.product,
                quantity=Decimal('1.0000'),
                movement_type='IN',
                recorded_by=self.staff_user,
            )
        self.url = reverse('inventory:movements_list')

    def test_first_page_shows_25_items(self):
        """First page shows 25 items."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 25)

    def test_second_page_shows_remaining_items(self):
        """Second page shows remaining items."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url, {'page': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 5)

    def test_pagination_controls_present(self):
        """Pagination controls are present when needed."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Page 1 of 2')
        self.assertContains(response, 'Next')


@override_settings(ROOT_URLCONF=__name__)
class ReadOnlyTests(TestCase):
    """Tests that the view is read-only."""

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
        self.movement = StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('5.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )
        self.url = reverse('inventory:movements_list')

    def test_get_does_not_create_movements(self):
        """GET request does not create any movements."""
        self.client.login(username='staffuser', password='testpass123')
        initial_count = StockMovement.objects.count()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockMovement.objects.count(), initial_count)

    def test_get_does_not_modify_stock(self):
        """GET request does not modify product stock."""
        self.client.login(username='staffuser', password='testpass123')
        initial_stock = self.product.stock_quantity
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock)

    def test_ledger_unchanged_after_filtered_get(self):
        """GET with filters does not modify ledger."""
        self.client.login(username='staffuser', password='testpass123')
        initial_count = StockMovement.objects.count()
        initial_movement_quantity = self.movement.quantity

        response = self.client.get(self.url, {
            'product': self.product.pk,
            'movement_type': 'IN',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockMovement.objects.count(), initial_count)
        self.movement.refresh_from_db()
        self.assertEqual(self.movement.quantity, initial_movement_quantity)


class MovementFilterFormTests(TestCase):
    """Tests for MovementFilterForm validation."""

    def test_empty_form_is_valid(self):
        """Empty form is valid (no filters)."""
        form = MovementFilterForm(data={})
        self.assertTrue(form.is_valid())

    def test_date_from_after_date_to_invalid(self):
        """date_from after date_to is invalid."""
        form = MovementFilterForm(data={
            'date_from': '2026-06-20',
            'date_to': '2026-06-10',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Date from cannot be after date to', str(form.errors))

    def test_valid_date_range(self):
        """Valid date range is accepted."""
        form = MovementFilterForm(data={
            'date_from': '2026-06-01',
            'date_to': '2026-06-30',
        })
        self.assertTrue(form.is_valid())

    def test_same_date_is_valid(self):
        """Same date for from and to is valid."""
        form = MovementFilterForm(data={
            'date_from': '2026-06-15',
            'date_to': '2026-06-15',
        })
        self.assertTrue(form.is_valid())


@override_settings(ROOT_URLCONF=__name__)
class EmptyStateTests(TestCase):
    """Tests for empty state display."""

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
        self.url = reverse('inventory:movements_list')

    def test_empty_list_shows_message(self):
        """Empty list shows appropriate message."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No stock movements found')

    def test_empty_filtered_list_shows_message(self):
        """Filtered list with no results shows appropriate message."""
        StockMovement.objects.create(
            product=self.product,
            quantity=Decimal('5.0000'),
            movement_type='IN',
            recorded_by=self.staff_user,
        )
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url, {'movement_type': 'OUT'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No stock movements found')
        self.assertContains(response, 'matching your filters')
