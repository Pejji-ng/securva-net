# PDF template (Phase 1)

This directory will contain the WeasyPrint HTML + CSS template for the generated Snapshot PDF.

Planned files (Phase 1):
- `template.html` — main report layout (cover + 8 section placeholders)
- `style.css` — Cabinet Grotesk + Newsreader fonts, dark theme, accent #7B68EE (matches existing Securva blog CSS)
- `sections/exec-summary.html` — executive summary partial
- `sections/headers.html` — security headers audit partial
- `sections/ssl-tls.html` — SSL/TLS posture partial
- `sections/ndpa.html` — NDPA compliance partial
- `sections/subdomains.html` — infrastructure footprint partial
- `sections/cves.html` — known CVE matching partial
- `sections/public-code.html` — GitHub dork exposure partial
- `sections/remediation.html` — remediation + Pejji upsell partial
- `assets/logo-securva.svg` — Securva brand mark
- `assets/fonts/` — embedded Cabinet Grotesk + Newsreader

Phase 1 will use babakizo.com as the sample data source (Kingsley approved 2026-04-15 01:36 UTC).
