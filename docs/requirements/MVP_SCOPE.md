# MVP Scope

This file defines what is in scope and out of scope for the Minimum Viable Product (MVP) of StockEasy.
The MVP is the version to be demonstrated and submitted for assessment.

---

## In scope for MVP

| Area | Feature | Priority |
|---|---|---|
| Auth | Login and logout | Must have |
| Auth | Three roles: Admin, Manager, Staff | Must have |
| Inventory | Unit management via admin | Must have |
| Inventory | Ingredient list view | Must have |
| Inventory | Ingredient cost per unit | Must have |
| Inventory | Stock quantity per ingredient | Must have |
| Recipes | Recipe creation via admin | Must have |
| Recipes | Recipe ingredient lines | Must have |
| Recipes | Recipe list view | Must have |
| Costing | Total recipe cost calculation | Must have |
| Costing | Cost per portion calculation | Must have |
| Costing | Suggested selling price at target margin | Must have |
| Costing | Costing summary table | Must have |
| Infrastructure | Docker Compose: web, db, redis | Must have |
| Infrastructure | PostgreSQL database | Must have |
| Infrastructure | Redis cache-ready configuration | Must have |
| Documentation | All docs/ files maintained throughout | Must have |

---

## Out of scope for MVP

| Feature | Reason deferred |
|---|---|
| CSV export | Requires stable data layer first |
| Reports app | No value without real costing data |
| Ingredient CRUD views | Admin interface sufficient for MVP |
| Recipe CRUD views | Admin interface sufficient for MVP |
| Stock adjustment forms | Post-MVP feature |
| Low stock alerts | Post-MVP feature |
| Waste logging | Post-MVP feature |
| Audit log | Post-MVP — added after models are stable |
| Celery / background tasks | Not required for MVP scope |
| Multi-venue support | Out of scope entirely |
| Per-employee statistics | Out of scope entirely |

---

## MVP milestone definition

The MVP is considered complete when:
1. Docker Compose starts all three services without errors.
2. Migrations run cleanly for accounts, inventory, and recipes.
3. A superuser can log in to the admin interface.
4. A regular user can log in to the application.
5. The inventory list, recipe list, and costing summary are all accessible and render correctly.
6. At least one recipe with ingredients produces a correct cost and suggested price.
7. All documentation files have been updated to reflect the current state.
8. First screenshot evidence has been collected per SCREENSHOT_CHECKLIST.md.
