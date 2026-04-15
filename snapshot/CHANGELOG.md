# Securva Snapshot — Changelog

All notable changes to the Snapshot product, per phase.

## Phase 0 — Scaffold (2026-04-15)

Initial repo scaffold. No functional code yet.

### Added
- `snapshot/` subdirectory at the root of securva-net repo
- Directory structure: `landing/`, `pdf-template/`, `scanner/`, `webhooks/`, `docs/`, `sample/`
- `README.md` with product overview, build phase table, pricing, ethical boundaries
- `CHANGELOG.md` (this file)
- Placeholder files in each subdirectory with clear "Phase X will populate this" markers
- `docs/product-spec.md` mirrored from `securva-disclosures/securva-snapshot-spec.md`
- `docs/launch-plan.md` with the 7-phase breakdown

### Notes
- Pricing tiers: Card ₦15K / Starter ₦30K / Pro ₦60K / Whitelabel ₦150K (adjustable in future phases without schema changes)
- Sample PDF subject: babakizo.com (Kingsley approved in TG at 2026-04-15 01:36 UTC)
- Build approach: subdirectory inside existing Pejji-ng/securva-net repo (not a new repo) per Kingsley's decision

### Not yet built (scheduled for Phase 1+)
- Sample PDF content
- Scanner orchestrator
- PDF rendering engine
- Payment webhooks
- Landing page
- End-to-end tests
- Any actual code

---
