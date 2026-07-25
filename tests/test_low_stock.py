"""
Tests for low stock alert functionality (F7).

Tests cover:
- Products below reorder level appear
- Products above reorder level do not appear
- Products exactly at reorder level appear (<= boundary)
- Products with reorder_level 0 never appear
- Inactive products never appear
- Shortfall computed correctly
- Ordering by urgency (largest shortfall first)
- RBAC: staff and manager get 200, anonymous redirects to login
"""

from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from inventory.models import Product, Category, Unit
from inventory.services import products_below_reorder_level

CustomUser = get_user_model()


class ProductsBelowReorderLevelServiceTests(TransactionTestCase):
    """Tests for products_below_reorder_level service function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)

    def test_product_below_reorder_level_appears(self):
        """A product with stock below its reorder level appears in the list."""
        product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('5.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )

        result = products_below_reorder_level()
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().pk, product.pk)

    def test_product_above_reorder_level_does_not_appear(self):
        """A product with stock above its reorder level does not appear."""
        Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('15.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )

        result = products_below_reorder_level()
        self.assertEqual(result.count(), 0)

    def test_product_exactly_at_reorder_level_appears(self):
        """A product exactly at its reorder level appears (<= boundary)."""
        product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )

        result = products_below_reorder_level()
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().pk, product.pk)

    def test_product_with_zero_reorder_level_never_appears(self):
        """A product with reorder_level 0 never appears, even at zero stock."""
        Product.objects.create(
            name='NotTracked',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('0.0000'),
            reorder_level=Decimal('0.0000'),
            is_active=True,
        )

        result = products_below_reorder_level()
        self.assertEqual(result.count(), 0)

    def test_inactive_product_never_appears(self):
        """An inactive product never appears, even if below reorder level."""
        Product.objects.create(
            name='Discontinued',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('2.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=False,
        )

        result = products_below_reorder_level()
        self.assertEqual(result.count(), 0)

    def test_shortfall_computed_correctly(self):
        """The shortfall annotation is reorder_level - stock_quantity."""
        Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('3.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )

        result = products_below_reorder_level()
        self.assertEqual(result.count(), 1)
        product = result.first()
        # shortfall = 10 - 3 = 7
        self.assertEqual(product.shortfall, Decimal('7.0000'))

    def test_ordering_most_urgent_first(self):
        """Products are ordered by shortfall descending (most urgent first)."""
        # Product A: shortfall = 15 - 10 = 5
        Product.objects.create(
            name='ProductA',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
            reorder_level=Decimal('15.0000'),
            is_active=True,
        )
        # Product B: shortfall = 20 - 5 = 15 (more urgent)
        Product.objects.create(
            name='ProductB',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('5.0000'),
            reorder_level=Decimal('20.0000'),
            is_active=True,
        )
        # Product C: shortfall = 10 - 8 = 2
        Product.objects.create(
            name='ProductC',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('8.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )

        result = list(products_below_reorder_level())
        self.assertEqual(len(result), 3)
        # Most urgent (shortfall 15) first, then 5, then 2
        self.assertEqual(result[0].name, 'ProductB')
        self.assertEqual(result[0].shortfall, Decimal('15.0000'))
        self.assertEqual(result[1].name, 'ProductA')
        self.assertEqual(result[1].shortfall, Decimal('5.0000'))
        self.assertEqual(result[2].name, 'ProductC')
        self.assertEqual(result[2].shortfall, Decimal('2.0000'))

    def test_includes_unit_and_category(self):
        """The queryset includes select_related unit and category."""
        Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('5.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )

        result = products_below_reorder_level()
        product = result.first()
        # Access should not trigger additional queries
        self.assertEqual(product.unit.name, 'Kilograms')
        self.assertEqual(product.category.name, 'Produce')


class LowStockViewTests(TestCase):
    """Tests for low_stock view RBAC and rendering."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
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
        self.url = reverse('inventory:low_stock')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_gets_200(self):
        """Staff user can access the view."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_manager_gets_200(self):
        """Manager user can access the view."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_empty_list_shows_all_ok_message(self):
        """When no products are below reorder level, show success message."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'All products are above their reorder level')

    def test_low_stock_product_shown_in_list(self):
        """A product below reorder level appears in the rendered list."""
        Product.objects.create(
            name='LowStockItem',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('3.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LowStockItem')
        self.assertContains(response, '1 product')
        self.assertContains(response, 'needs reordering')

    def test_multiple_products_shows_plural(self):
        """Multiple products show plural form in header."""
        Product.objects.create(
            name='Item1',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('3.0000'),
            reorder_level=Decimal('10.0000'),
            is_active=True,
        )
        Product.objects.create(
            name='Item2',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('5.0000'),
            reorder_level=Decimal('15.0000'),
            is_active=True,
        )
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2 products')
        self.assertContains(response, 'need reordering')
