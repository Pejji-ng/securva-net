# Securva Snapshot

**Securva Snapshot** is a self-serve ₦30,000 (or $29 USD) website security assessment delivered as a 12-20 page PDF within 5 minutes of payment.

Customer enters a domain on securva.net/snapshot, pays via Gumroad or Paystack, an automated pipeline runs 7 security checks against that domain, generates a branded PDF report, and emails it to them. Zero humans in the delivery loop.

This product is the Phase 2 priority in the Securva strategic roadmap. It is the first revenue-generating product for Securva and functions as the entry point to a natural upsell ladder (Snapshot → Continuous Monitoring → Pejji remediation).

---

## Directory layout

```
snapshot/
├── README.md              — this file
├── CHANGELOG.md           — per-phase shipping log
├── docs/
│   ├── product-spec.md    — full product specification (mirrored from securva-disclosures)
│   ├── architecture.md    — data pipeline + infrastructure diagram
│   ├── pricing.md         — current pricing tiers + change log
│   ├── support-playbook.md — what to say when a customer emails with a complaint
│   └── launch-plan.md     — 7-phase launch plan with checkpoints
├── landing/               — Astro pages for securva.net/snapshot
├── pdf-template/          — HTML + CSS template rendered by WeasyPrint
│   ├── template.html      — main report layout
│   ├── style.css          — Cabinet Grotesk + Newsreader fonts, dark theme
│   └── sections/          — per-section partial templates
├── scanner/               — Python orchestrator that runs the 7 checks
│   ├── orchestrator.py    — main entry point (domain in, JSON out)
│   ├── checks/            — individual scan modules
│   │   ├── headers.py     — HTTP security headers (reuses securva-api)
│   │   ├── ssl_tls.py     — openssl wrapper for cert + protocol checks
│   │   ├── ndpa.py        — NDPA compliance scraper
│   │   ├── subdomains.py  — subfinder + dnsx wrapper
│   │   ├── cves.py        — nuclei integration for CVE matching
│   │   ├── dorks.py       — GitHub code search for public secrets (reuses dork pipeline)
│   │   └── remediation.py — maps findings to Pejji upsell quotes
│   └── tests/             — unit + integration tests
├── webhooks/              — Cloudflare Workers for Gumroad + Paystack
│   ├── gumroad-webhook.js
│   ├── paystack-webhook.js
│   └── deploy-notes.md
└── sample/                — the downloadable sample PDF for sales demos
    └── snapshot-sample-babakizo-com.pdf  — generated in Phase 1 for babakizo.com
```

---

## Build phases

Tracked in `docs/launch-plan.md`. High level:

| Phase | Deliverable | Estimated time | Status |
|---|---|---|---|
| 0 | Repo scaffold + CI/CD + placeholder files | 1 hour | in progress |
| 1 | Sample PDF for babakizo.com | 6 hours | pending |
| 2 | Scanner orchestrator | 8 hours | pending |
| 3 | PDF rendering engine | 4 hours | pending |
| 4 | Payment + fulfillment | 8 hours | pending |
| 5 | Landing page + sales copy | 4 hours | pending |
| 6 | Dry run + testing | 2 hours | pending |
| 7 | Soft launch + first sales | monitoring | pending |

Total estimated: ~33 hours coding + 5 days monitoring = 10 calendar days from greenlight to first paying customer.

---

## Pricing (v1, adjustable)

| Tier | Price (NGN) | Price (USD) | Includes |
|---|---|---|---|
| Card | ₦15,000 | $10 | Just the report, no follow-up |
| **Starter** ⭐ | **₦30,000** | **$29** | Report + 30-min Q&A call |
| Pro | ₦60,000 | $49 | Starter + NDPA add-on + 90-day re-scan |
| Whitelabel | ₦150,000 | $99 | Pro + customer-branded report, no Securva logo |

---

## Ethical + legal boundaries

This product is designed within strict ethical boundaries:

- Scans run ONLY against the domain the customer provides (terms of service require a "I own or have authorization to scan this domain" checkbox)
- No active exploitation — passive discovery only
- No authenticated testing — scanner behaves like an anonymous visitor
- No attempt to exfiltrate data
- Output can be used for internal security review only — NOT as a penetration test certification
- Data retention: customer email + scan results kept for 90 days then automatically deleted
- NDPA-compliant on our side

---

## Related projects

- **Continuous Monitoring (Play 3):** the recurring subscription product. Customers who want ongoing monitoring after a one-shot Snapshot graduate into monitoring at ₦15K/month per domain. Spec: `~/blessedops-projects/securva-disclosures/securva-monitoring-spec.md`
- **Pejji remediation (pejji.com):** where Snapshot customers who need their findings fixed get quoted at ₦60K-1.5M+ for implementation work
- **Fintech Due Diligence Report (Play 17):** premium one-shot engagement at $5-15K for VCs and insurance underwriters, uses same scanner pipeline at deeper scope

---

## Contacts

- Product lead: Kingsley Olukanni (hello@securva.net)
- Repo: github.com/Pejji-ng/securva-net (snapshot/ subdirectory)
- Live: securva.net/snapshot (pending Phase 5 launch)
