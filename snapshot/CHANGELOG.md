# Securva Snapshot - Changelog

All notable changes to the Snapshot product, per phase.

## v1.1 - Section 10 Vendor Compliance (2026-04-23)

### Added
- **Section 10 of the PDF: Vendor Compliance / NTAA 2026 §45 Exposure.** Renders when the caller supplies a vendor CSV. Summary table with risk distribution and ₦5M/vendor penalty exposure estimate, then red/amber/green vendor tables with remediation hints sourced from the TIN-verify module.
- `render.py`: `_load_vendor_findings()` + `vendor_jsonl` arg to `prepare_template_context()`. `--vendor-jsonl` CLI flag.
- `api.py`: `_invoke_tin_verify()` subprocess wrapper (parallel to `_invoke_web2_scanner`). `ScanRequest.vendor_csv_b64` optional field. `TIN_VERIFY_PATH` + `TIN_VERIFY_TIMEOUT_SEC` env overrides. Size limit of 256 KB on the decoded vendor CSV. API version bumped 0.4.1 -> 0.4.2.
- Response payload: `vendor_findings_included` boolean flag.

### Notes
- TIN-verify module lives on the research box at `~/bounty/tools/tin-verify/` (Buddy's v0, schema and privacy contract documented in its README).
- Cache is verdict-only by design - no raw TINs, phone numbers, or email addresses persist. The temp vendor CSV is deleted inside `_invoke_tin_verify()` as soon as the CLI returns.
- Absence of a vendor list is the default path: `{% if vendor_findings %}` guards Section 10, so the web-only Snapshot flow renders unchanged.
- NTAA 2026 §45 framing: ₦5,000,000 per-vendor penalty for engaging vendors without a valid NRS-issued TIN. First-mover SME category per the Vendor Compliance Sweep product spec.

### Integration test
- Syntax check: `python3 -m py_compile` passes on api.py + render.py.
- End-to-end PDF render verification: Buddy (box-Claude) pulls this branch and fires against the 25-vendor stress-test JSONL from phase-intel.db. Ships as part of this PR verification.

---

## Phase 0 - Scaffold (2026-04-15)

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
