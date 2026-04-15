# Scanner orchestrator (Phase 2)

This directory will contain the Python orchestrator that runs the 7 security checks against a customer's domain.

Planned structure (Phase 2):

```
scanner/
├── orchestrator.py         — main entry point (domain in, JSON out)
├── pdf_renderer.py         — wires orchestrator JSON into PDF template (Phase 3)
├── queue_runner.py         — cron runner that picks up new jobs from customer DB (Phase 4)
├── checks/
│   ├── __init__.py
│   ├── headers.py          — HTTP security headers (reuses securva-api)
│   ├── ssl_tls.py          — openssl s_client wrapper
│   ├── ndpa.py             — NDPA compliance scraper
│   ├── subdomains.py       — subfinder + dnsx wrapper
│   ├── cves.py             — nuclei CVE matching
│   ├── dorks.py            — GitHub code search (reuses dork pipeline)
│   └── remediation.py      — Pejji upsell quote mapper
├── tests/
│   ├── test_orchestrator.py
│   ├── test_headers.py
│   ├── test_ssl_tls.py
│   └── fixtures/           — sample scan outputs for testing
└── requirements.txt        — Python deps (weasyprint, requests, etc.)
```

Phase 2 trigger: Phase 1 merge (PDF template + sample report for babakizo.com in place).
