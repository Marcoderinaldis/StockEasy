# Requirements

This file documents the functional and non-functional requirements for StockEasy.

---

## Project overview

StockEasy is a web-based stock and recipe costing management system designed for single-venue hospitality SMEs.
It enables managers and staff to track ingredient inventory, define recipes, and calculate accurate food costs and suggested selling prices.

---

## Functional requirements

### Authentication and authorisation
- FR-01: The system must provide a login page accessible to all roles.
- FR-02: The system must support three user roles: Admin, Manager, Staff.
- FR-03: Access to all views must require authentication.
- FR-04: Role must be visible in the navigation bar after login.

### Inventory
- FR-05: The system must allow units of measure to be defined (e.g. kg, litre, each).
- FR-06: The system must allow ingredients to be created with a name, unit, and cost per unit.
- FR-07: The system must display all ingredients in a list view.
- FR-08: Each ingredient must record current stock quantity.

### Recipes
- FR-09: The system must allow recipes to be created with a name, description, and number of portions.
- FR-10: Each recipe must support one or more ingredient lines with quantity.
- FR-11: The system must display all recipes in a list view.
- FR-12: Recipes must record the user who created them.

### Costing
- FR-13: The system must calculate the total ingredient cost for each recipe.
- FR-14: The system must calculate the cost per portion for each recipe.
- FR-15: The system must suggest a selling price per portion based on a target gross margin.
- FR-16: The costing view must display all recipes with their cost summary.

---

## Non-functional requirements

- NFR-01: The application must run inside Docker containers for local development.
- NFR-02: The database must be PostgreSQL.
- NFR-03: All pages must be responsive using Bootstrap 5.
- NFR-04: Authentication must use Django's built-in session-based system.
- NFR-05: No personally identifiable information beyond username and email must be stored.
- NFR-06: The codebase must follow consistent naming conventions throughout.

---

## Out of scope for MVP

- CSV export and reporting
- Per-employee statistics
- Email notifications
- POS integration
- AI or machine learning features
- Multi-venue support

---

## Sprint 2 Deliverables

### Models Created (9 total)

| Model | App | Key Features |
|-------|-----|--------------|
| Unit | inventory | Weight/Volume/Count types, conversion_to_base for unit conversion |
| Category | inventory | Product grouping with is_active flag |
| Product | inventory | Central stock entity, stock_quantity (service-layer only), reorder_level |
| PurchasePrice | inventory | Historical pricing with effective_from/effective_to |
| StockMovement | inventory | **Append-only**, 6 movement types, double-void prevention |
| WasteRecord | waste | Linked to StockMovement, 6 standardised waste categories |
| Recipe | recipes | yields_quantity + yields_unit for portion calculation |
| RecipeIngredient | recipes | Unit can differ from product.unit (validated in service layer) |
| CustomUser | accounts | 3 roles: Admin, Manager, Staff |

### Key Constraints

1. **StockMovement is append-only** — no updates or deletes ever allowed
2. **Double-void prevention** — VOID rejected if another VOID exists for same product within 5 minutes
3. **Unit conversion validation** — enforced everywhere quantities appear
4. **All stock mutations via service layer** — direct Product.stock_quantity updates forbidden
5. **6 standardised waste categories**:
   - Product expired
   - Delivery damaged
   - Counting error
   - Spillage/accidental waste
   - Void—entered in error
   - Other

### Service Layer Stubs (Sprint 3 Implementation)

- `inventory/services.py`: record_stock_in(), record_stock_out(), record_waste(), void_movement()
- `waste/services.py`: record_waste_via_movement()
- `recipes/services.py`: calculate_recipe_cost()
- `costing/services.py`: calculate_product_cost()

### Seed Data

- 5 Units (kg, g, litres, ml, items)
- 3 Categories (Produce, Dairy, Proteins)
- 3 Products with initial PurchasePrices
- Admin user (username: admin)
