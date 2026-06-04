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
