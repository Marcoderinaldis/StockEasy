# Screenshot Checklist

This file tracks all screenshots required as evidence for the project.
Screenshots must be taken at the correct development stage — not reconstructed later.

---

## Format

Each screenshot must be saved as: `docs/screenshots/SC-XXX_description.png`

---

## Milestone 1 — Skeleton and infrastructure

| ID | Description | Required at | Taken |
|---|---|---|---|
| SC-001 | Docker Desktop showing all three containers running (web, db, redis) | After first `docker compose up` | [ ] |
| SC-002 | Terminal output of `docker compose ps` with all services Up | After first `docker compose up` | [ ] |
| SC-003 | Terminal output of `python manage.py migrate` completing without errors | After first migration | [ ] |
| SC-004 | Django admin login page at localhost:8000/admin | After first migrate | [ ] |
| SC-005 | Django admin dashboard showing CustomUser and Inventory models | After superuser created | [ ] |
| SC-006 | CustomUser list in admin showing role column | After superuser created | [ ] |
| SC-007 | VS Code Explorer showing full project folder structure | After skeleton complete | [ ] |
| SC-008 | Application home dashboard at localhost:8000 after login | After first login | [ ] |
| SC-009 | Inventory list page at localhost:8000/inventory/ | After first login | [ ] |
| SC-010 | Recipe list page at localhost:8000/recipes/ | After first login | [ ] |
| SC-011 | Costing summary page at localhost:8000/costing/ | After first login | [ ] |

---

## Milestone 2 — First real data

| ID | Description | Required at | Taken |
|---|---|---|---|
| SC-012 | Admin — creating a Unit (e.g. kg) | First data entry | [ ] |
| SC-013 | Admin — creating an Ingredient with cost | First data entry | [ ] |
| SC-014 | Admin — creating a Recipe with RecipeIngredient lines | First data entry | [ ] |
| SC-015 | Costing page showing calculated total cost and suggested price | After first recipe created | [ ] |

---

## Notes

- File naming: SC-001_docker_containers_running.png
- Resolution: minimum 1280x720
- No personal information visible in screenshots (no real names, no real credentials)
- Browser address bar must be visible in all application screenshots
