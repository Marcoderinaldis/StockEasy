"""
Tests for the Costing section (Feature 8).

Tests cover:
- Product.current_price property
- set_product_price service (append-only, closing old prices, validation)
- Costing views (RBAC, listing, history, update)
- Service-only price mutation (no direct model manipulation in views)
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory.models import Product, Category, Unit, PurchasePrice
from costing.services import set_product_price, PriceValidationError

CustomUser = get_user_model()


class ProductCurrentPricePropertyTests(TestCase):
    """Tests for Product.current_price property."""

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
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )

    def test_current_price_returns_active_price(self):
        """current_price returns the price with effective_to=null."""
        price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        self.assertEqual(self.product.current_price, price)

    def test_current_price_returns_none_when_no_price(self):
        """current_price returns None if no active price exists."""
        self.assertIsNone(self.product.current_price)

    def test_current_price_returns_none_when_all_closed(self):
        """current_price returns None if all prices are closed."""
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=timezone.now(),  # Closed
        )

        self.assertIsNone(self.product.current_price)

    def test_current_price_returns_latest_when_multiple_active(self):
        """If multiple active prices exist, return the latest by effective_from."""
        # Create older price
        older_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # Create newer price (auto_now_add will make it newer)
        newer_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('3.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # The newer one should be returned
        self.assertEqual(self.product.current_price, newer_price)


class SetProductPriceServiceTests(TransactionTestCase):
    """Tests for the set_product_price service function."""

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
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )

    def test_set_price_creates_new_active_price(self):
        """set_product_price creates a new active price."""
        new_price = set_product_price(
            product=self.product,
            unit_price=Decimal('5.00'),
            user=self.user,
        )

        self.assertIsNotNone(new_price)
        self.assertEqual(new_price.unit_price, Decimal('5.00'))
        self.assertEqual(new_price.product, self.product)
        self.assertEqual(new_price.created_by, self.user)
        self.assertIsNone(new_price.effective_to)  # Active
        self.assertEqual(new_price.currency, 'GBP')

    def test_set_price_closes_old_active_price(self):
        """Adding a new price closes the old active price."""
        # Create initial price
        old_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # Set new price
        new_price = set_product_price(
            product=self.product,
            unit_price=Decimal('3.00'),
            user=self.user,
        )

        # Old price should be closed
        old_price.refresh_from_db()
        self.assertIsNotNone(old_price.effective_to)

        # New price should be active
        self.assertIsNone(new_price.effective_to)

    def test_set_price_leaves_only_one_active(self):
        """After setting a price, exactly one active price remains."""
        # Create two initial active prices (edge case)
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # Set new price
        set_product_price(
            product=self.product,
            unit_price=Decimal('3.00'),
            user=self.user,
        )

        # Only one active price should exist
        active_prices = PurchasePrice.objects.filter(
            product=self.product,
            effective_to__isnull=True
        )
        self.assertEqual(active_prices.count(), 1)
        self.assertEqual(active_prices.first().unit_price, Decimal('3.00'))

    def test_set_price_does_not_modify_old_unit_price(self):
        """Old price's unit_price is never modified (append-only)."""
        old_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )
        original_unit_price = old_price.unit_price

        # Set new price
        set_product_price(
            product=self.product,
            unit_price=Decimal('3.00'),
            user=self.user,
        )

        # Old price's unit_price unchanged
        old_price.refresh_from_db()
        self.assertEqual(old_price.unit_price, original_unit_price)

    def test_set_price_validates_positive_price(self):
        """Zero or negative price raises PriceValidationError."""
        with self.assertRaises(PriceValidationError):
            set_product_price(
                product=self.product,
                unit_price=Decimal('0'),
                user=self.user,
            )

        with self.assertRaises(PriceValidationError):
            set_product_price(
                product=self.product,
                unit_price=Decimal('-1.00'),
                user=self.user,
            )

    def test_set_price_validates_numeric_input(self):
        """Invalid price input raises PriceValidationError."""
        with self.assertRaises(PriceValidationError):
            set_product_price(
                product=self.product,
                unit_price='not_a_number',
                user=self.user,
            )

    def test_set_price_quantizes_to_two_decimal_places(self):
        """Price is quantized to 2 decimal places."""
        new_price = set_product_price(
            product=self.product,
            unit_price=Decimal('2.567'),
            user=self.user,
        )

        self.assertEqual(new_price.unit_price, Decimal('2.57'))

    def test_set_price_accepts_string_input(self):
        """Price can be provided as a string."""
        new_price = set_product_price(
            product=self.product,
            unit_price='5.99',
            user=self.user,
        )

        self.assertEqual(new_price.unit_price, Decimal('5.99'))

    def test_set_price_accepts_float_input(self):
        """Price can be provided as a float."""
        new_price = set_product_price(
            product=self.product,
            unit_price=5.99,
            user=self.user,
        )

        self.assertEqual(new_price.unit_price, Decimal('5.99'))


class CostingHomeViewTests(TestCase):
    """Tests for the costing home view."""

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
        self.url = reverse('costing:costing_home')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_can_view(self):
        """Staff user can view costing home."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product Prices')

    def test_manager_can_view(self):
        """Manager user can view costing home."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_view(self):
        """Admin user can view costing home."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_lists_products_with_current_price(self):
        """View lists products with their current prices."""
        price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=None,
        )

        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'Tomatoes')
        self.assertContains(response, '2.50')

    def test_staff_does_not_see_update_button(self):
        """Staff user does not see Update Price button."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertNotContains(response, 'Update Price')

    def test_manager_sees_update_button(self):
        """Manager user sees Update Price button."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'Update Price')


class PriceHistoryViewTests(TestCase):
    """Tests for the price history view."""

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
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('costing:price_history', args=[self.product.pk])

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_can_view(self):
        """Staff user can view price history."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Price History')
        self.assertContains(response, 'Tomatoes')

    def test_shows_active_and_closed_prices(self):
        """View shows both active and closed prices."""
        # Create closed price
        closed_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=timezone.now(),
        )

        # Create active price
        active_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=None,
        )

        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, '2.00')
        self.assertContains(response, '2.50')
        self.assertContains(response, 'Current')
        self.assertContains(response, 'Closed')


class UpdatePriceViewTests(TestCase):
    """Tests for the update price view."""

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
        self.url = reverse('costing:update_price')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_get_403(self):
        """Staff user gets 403 on GET."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_post_403(self):
        """Staff user gets 403 on POST."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'unit_price': '5.00',
        })
        self.assertEqual(response.status_code, 403)

    def test_manager_can_access(self):
        """Manager user can access update price view."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update Product Price')

    def test_admin_can_access(self):
        """Admin user can access update price view."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_successful_post_creates_price_via_service(self):
        """Successful POST creates a new price using the service."""
        # Create initial price
        old_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=None,
        )

        self.client.login(username='manageruser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'unit_price': '3.99',
        })

        # Redirects on success
        self.assertEqual(response.status_code, 302)

        # Old price is closed
        old_price.refresh_from_db()
        self.assertIsNotNone(old_price.effective_to)

        # New price is active
        new_price = self.product.current_price
        self.assertIsNotNone(new_price)
        self.assertEqual(new_price.unit_price, Decimal('3.99'))
        self.assertEqual(new_price.created_by, self.manager_user)

    def test_post_with_preselected_product(self):
        """POST to product-specific URL works."""
        url = reverse('costing:update_price_for_product', args=[self.product.pk])

        self.client.login(username='adminuser', password='testpass123')
        response = self.client.post(url, {
            'product': self.product.pk,
            'unit_price': '4.50',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.current_price.unit_price, Decimal('4.50'))

    def test_invalid_price_shows_error(self):
        """Invalid price shows form error."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'unit_price': '0',  # Invalid
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ensure this value is greater than or equal to 0.01')


class ServiceOnlyPriceMutationTests(TestCase):
    """Tests to ensure price mutation only happens via service."""

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
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('costing:update_price')

    def test_view_uses_service_for_price_creation(self):
        """View uses set_product_price service, not direct model creation."""
        with patch('costing.views.set_product_price') as mock_service:
            mock_service.return_value = PurchasePrice(
                product=self.product,
                unit_price=Decimal('5.00'),
                currency='GBP',
            )

            self.client.login(username='adminuser', password='testpass123')
            self.client.post(self.url, {
                'product': self.product.pk,
                'unit_price': '5.00',
            })

            mock_service.assert_called_once()
            call_args = mock_service.call_args
            self.assertEqual(call_args.kwargs['product'], self.product)
            self.assertEqual(call_args.kwargs['unit_price'], Decimal('5.00'))
            self.assertEqual(call_args.kwargs['user'], self.admin_user)


class NavbarCostingLinkTests(TestCase):
    """Tests for the Costing link in the navbar."""

    def setUp(self):
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.url = reverse('core:home')

    def test_costing_link_visible_to_authenticated_users(self):
        """Costing link is visible to authenticated users."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'Costing')
        self.assertContains(response, reverse('costing:costing_home'))
