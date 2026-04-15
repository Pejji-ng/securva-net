# Securva Snapshot — 7-Phase Launch Plan

**Date:** 2026-04-15 Day 6
**Goal:** Zero to first paying customer in 10 calendar days from greenlight

---

## Phase 0 — Scaffold (today, 1 hour)

**Status:** in progress

**Deliverable:** empty subdirectory structure + README + PR open

**Work:**
- Create `/snapshot/` directory tree
- Write product README
- Mirror the product spec from disclosures folder
- Open PR #1 "feat: Snapshot Phase 0 scaffold"

**Kingsley's role:** review PR, merge if good. Takes 5 minutes.

---

## Phase 1 — Sample PDF for babakizo.com (Day 1-2, 6 hours)

**Status:** pending Phase 0 merge

**Deliverable:** a real, downloadable `snapshot-sample-babakizo-com.pdf` in `snapshot/sample/`

**Work:**
- Build `snapshot/pdf-template/template.html` in HTML + CSS using WeasyPrint
- Match existing securva.net theme (Cabinet Grotesk + Newsreader, dark, accent #7B68EE)
- Write all 8 section templates (exec summary, headers, SSL/TLS, NDPA, subdomains, CVEs, public code exposure, remediation)
- Run a one-off scan against babakizo.com using existing tools
- Generate production-quality sample PDF
- Open PR #2 "feat: add snapshot PDF template + sample report for babakizo.com"

**Kingsley's role:**
- Review the generated PDF
- Approve the visual design or request changes
- 15-30 min review

---

## Phase 2 — Scanner orchestrator (Day 3-4, 8 hours)

**Status:** pending Phase 1 merge

**Deliverable:** `snapshot/scanner/orchestrator.py` that takes a domain and produces structured JSON covering all 8 report sections

**Work:**
- Write `orchestrator.py` as the main entry point
- Write `checks/headers.py` — reuses existing securva-api endpoint
- Write `checks/ssl_tls.py` — wraps openssl s_client
- Write `checks/ndpa.py` — NDPA compliance scraper (ports Pejji contact form pattern)
- Write `checks/subdomains.py` — wraps subfinder + dnsx on box
- Write `checks/cves.py` — wraps nuclei with template matching
- Write `checks/dorks.py` — reuses GitHub dork pipeline for the specific customer's GitHub org
- Write `checks/remediation.py` — maps findings to Pejji upsell quotes
- Add unit tests + integration tests for each module
- Rate-limit policy: max 1 concurrent scan per domain, 10-second delay between probes
- Open PR #3 "feat: scanner orchestrator + integration tests"

**Kingsley's role:**
- Test a manual scan yourself against a domain of your choice
- Approve rate-limiting policy
- 30-60 min review

---

## Phase 3 — PDF rendering engine (Day 5, 4 hours)

**Status:** pending Phase 2 merge

**Deliverable:** a single Python script `snapshot/scanner/pdf_renderer.py` that takes the orchestrator's JSON output and produces a finished PDF in under 90 seconds

**Work:**
- Wire orchestrator JSON into the WeasyPrint template from Phase 1
- Add matplotlib-generated grade chart
- Add deterministic report IDs (SEC-SS-YYYYMMDD-NNNN)
- Add customer domain branding on cover page
- Test with 10 different real domains to catch edge cases
- Open PR #4 "feat: PDF rendering engine + edge case handling"

**Kingsley's role:**
- Review 3-5 generated PDFs with you on TG
- Flag any formatting or content issues
- 30 min review

---

## Phase 4 — Payment + fulfillment plumbing (Day 6-7, 8 hours)

**Status:** pending Phase 3 merge

**Deliverable:** end-to-end flow: customer pays → 5 minutes later PDF lands in their inbox

**Work (desktop Claude):**
- Build `snapshot/webhooks/gumroad-webhook.js` — Cloudflare Worker
- Build `snapshot/webhooks/paystack-webhook.js` — Cloudflare Worker
- Build `snapshot/scanner/queue_runner.py` — cron runner that picks up new jobs, runs scan, renders PDF, emails
- Wire Resend or Mailgun for email delivery with branded HTML template
- Set up SQLite customer DB on the box (first 1000 customers)
- Open PR #5 "feat: payment webhooks + fulfillment pipeline"

**Kingsley's role (KYC-gated steps I cannot do):**
- Create a Gumroad product with the 4 tier variants
- Create a Paystack payment flow
- Configure webhook URLs in each provider's dashboard
- Set up Resend/Mailgun account
- Provide webhook secrets + API keys via the secure installation pattern (sudo heredoc stdin paste, same pattern as vein Worker setup from Day 4)
- 60-90 min of setup clicks

---

## Phase 5 — Landing page + sales copy (Day 8, 4 hours)

**Status:** pending Phase 4 merge

**Deliverable:** live landing page at `securva.net/snapshot` that customers can visit and buy from

**Work:**
- Build `snapshot/landing/` Astro pages matching existing securva.net design
- Write sales copy targeting Nigerian SMEs, Lagos startup founders, agencies, journalists
- Pricing table with 4 tiers
- FAQ section (10 questions)
- Sample PDF download CTA
- "Buy now" CTAs routing to Gumroad or Paystack based on currency
- SEO + structured data markup
- Open PR #6 "feat: snapshot landing page + sales copy"

**Kingsley's role:**
- Review copy and edit anything that feels wrong
- Provide testimonials or trust badges if you have them
- 30 min review

---

## Phase 6 — Dry run + internal testing (Day 9, 2 hours)

**Status:** pending Phase 5 merge

**Deliverable:** a product that survives first real customer contact

**Work (desktop Claude):**
- Monitor your dry run in real time
- Fix anything that breaks
- Add fallback error handling for each failure mode
- Write a short support playbook

**Kingsley's role:**
- Make a real ₦15K test purchase yourself
- Verify the PDF lands in your inbox within 5 minutes
- Click every link, test every edge case
- Refund yourself after verification
- 30-60 min testing

---

## Phase 7 — Soft launch + first sales (Day 10-14, monitoring)

**Status:** pending Phase 6 approval

**Deliverable:** first paying customer

**Work (Kingsley):**
- Announce on your existing channels:
  - X/Twitter personal brand post
  - Pejji WhatsApp channel
  - TechCabal Slack
  - Nairaland tech section
  - 1-2 Nigerian Facebook fintech groups
  - Email to existing Pejji client list
  - 20 personal DMs to Nigerian tech network
- Reply to questions and DMs
- Process support tickets via hello@securva.net

**Work (desktop Claude):**
- Monitor customer DB every 30 minutes during first week
- Alert you via TG on any failed jobs or errors
- Hot-patch bugs using NOPASSWD on box
- Track metrics and send you a daily performance summary

**Target outcomes:**
- First paying customer: Day 10-12
- First 10 customers: Day 14-21
- Product/market fit signal: Day 30

---

## Risk + mitigation

**Risk 1: Gumroad or Paystack integration breaks.** Mitigation: test in Phase 6 with a real test payment before launch. Hot-patch fast.

**Risk 2: Scanner hits Cloudflare or AWS WAF on customer targets and gets blocked.** Mitigation: polite User-Agent, rate limiting, clear messaging in the FAQ ("if your scan failed, it may be because your WAF blocked us — try disabling during scan").

**Risk 3: Customer scans a domain they do not own.** Mitigation: TOS checkbox, legal disclaimer, manual review for high-scope customers (agency tier), refund policy if abused.

**Risk 4: PDF generation is slow or unreliable.** Mitigation: WeasyPrint is deterministic. Test against 10+ domains in Phase 3. Retry logic in Phase 4.

**Risk 5: First customer is the worst customer (wants a refund, complains loudly, writes negative review).** Mitigation: support playbook includes a "please tell us what went wrong, we will refund you and learn from it" template. Treat early customers as co-designers not pure buyers.

---

## Success metrics

By Day 30 after launch:

- 10+ paying customers
- < 5% refund rate
- 4-star average rating or better (once we have a review mechanism)
- At least 1 Pejji remediation quote generated from a Snapshot finding
- At least 1 piece of organic user-generated content (tweet, LinkedIn post, blog mention)

By Day 90:

- 60+ paying customers
- ₦1.8M/month recurring (see product spec for details)
- At least 3 Pejji fix engagements originated from Snapshot
- First Continuous Monitoring customer upsold from Snapshot (Phase 3 revenue product begins)
