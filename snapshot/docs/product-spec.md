# Securva Snapshot — Product Specification (v0.1 DRAFT)

**Date:** 2026-04-14 Day 5
**Status:** DRAFT, needs Kingsley review before any build
**Aligned with:** `project_securva_roadmap_v2.md` Phase 2 priority ("Gumroad Snapshot $29 = validate before building SaaS")
**Author:** desktop Claude with Kingsley's direction

---

## 1. What it is

A **self-serve $29 website security assessment** delivered as a 12-20 page PDF within 5 minutes of payment. Customer enters a domain, pays via Gumroad or Paystack, an automated pipeline runs the Securva scanner stack against the domain, and a branded PDF report lands in their email.

**Positioning:** "The Nigerian cyber due diligence report that fits in your pocket." It is not a 50-page enterprise audit. It is not a compliance certification. It is the security equivalent of a car inspection report — fast, affordable, honest, useful.

**Target customer:**
- Nigerian SME owners who want to know if their website is leaking anything
- Lagos startup founders preparing for investor diligence
- Nigerian marketing agencies doing light-touch competitive analysis on behalf of clients
- Nigerian journalists investigating companies for stories
- Pejji prospects we can upsell from `securva.net/scan` → deeper report

## 2. Why this is the right first revenue product

Three reasons:

1. **It already exists in your 90-day plan.** The v2 Securva roadmap explicitly says "Gumroad Snapshot $29 = Phase 2 priority (validate before building SaaS)". I am not inventing something new, I am productizing something you already decided to build.

2. **Every piece of the pipeline already exists.** The scanner is live at api.securva.net. The header checker works. The nuclei integration is on the box. The NDPA compliance scraper is draftable in an afternoon. The only missing piece is the PDF generator + Gumroad fulfillment plumbing.

3. **Every sale feeds the Pejji funnel naturally.** The PDF ends with a remediation section that quotes Pejji's fix packages (Card ₦60K, Starter ₦150K, Growth ₦300K, Pro ₦800K+, Pro Max ₦1.5M+). $29 upfront, potential ₦60K-1.5M+ downstream on a small percentage of conversions.

## 3. The 8 sections of the Snapshot report

Each section is 1-2 pages. Total target: 12-16 pages including cover + back matter.

### Section 1: Executive Summary (1 page)
- Domain scanned
- Overall grade (A / B / C / D / F) with color-coded badge
- Top 3 findings in plain English
- "What this means for your business" summary
- 3 recommended actions with cost estimate in naira

### Section 2: Security Headers Analysis (2 pages)
- Per-header pass/fail table (10 headers total: HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, X-XSS-Protection, Cross-Origin-Opener-Policy, Cross-Origin-Embedder-Policy, Cross-Origin-Resource-Policy)
- Why each missing header matters in 1-2 sentences of plain language
- Pulled from the existing securva.net scanner output, no new work

### Section 3: SSL / TLS Posture (1 page)
- Certificate expiry date
- Issuer (free Let's Encrypt vs paid DigiCert vs self-signed)
- TLS protocol versions allowed (1.0 and 1.1 = fail, 1.2 and 1.3 = pass)
- Weak cipher detection
- Grade: A / B / C / F
- Pulled from an `openssl s_client` call wrapped in Python on the box

### Section 4: NDPA Compliance Check (2 pages)
- Cookie consent banner present? Y/N
- Privacy policy page present? Y/N
- Privacy policy mentions NDPA / NDPC? Y/N
- Contact email for data requests visible? Y/N
- Cross-border data transfer disclosure? Y/N
- NDPA section ends with: "This check is not a legal audit. If you store Nigerian user data and your grade here is below B, you should consider a full compliance review."
- Builds on the existing Pejji NDPA scraper pattern

### Section 5: Subdomain & Infrastructure Footprint (2 pages)
- List of publicly discovered subdomains (from subfinder + dnsx on box)
- Hosting provider breakdown (Cloudflare, AWS, Azure, self-hosted)
- Unusual subdomains flagged (admin., dev., staging., test., backup., old., internal.)
- Exposed Git repositories (/.git/HEAD, /.git/config)
- Known cloud misconfiguration patterns

### Section 6: Known Vulnerability Check (1-2 pages)
- Tech stack fingerprint (detected frameworks, CMS, CDN, JS libraries)
- Known CVEs matching the detected versions (cross-reference against NVD data)
- Severity: critical / high / medium / low / info
- One-line remediation for each

### Section 7: Public Code Exposure (1 page)
- GitHub organization name guess (from domain + WHOIS)
- If any public repos under that org contain files that match our dork pipeline patterns (.env, config.js with secrets, service-account JSON, etc.), flag them
- Reuses the existing dork pipeline
- Note: this section is the differentiator. No Nigerian competitor does this.

### Section 8: Remediation Roadmap + Pejji Upsell (2 pages)
- Findings grouped into: Critical (fix this week), High (fix this month), Medium (fix this quarter), Low (educational)
- For each group, estimated hours to fix in-house OR fixed-price quote from Pejji:
  - Card tier (₦60K): quick-win header + SSL fixes for static sites
  - Starter (₦150K): landing page rebuild with security headers + NDPA + SSL fix
  - Growth (₦300K): multi-page business site with monitoring + booking
  - Pro (₦800K+): full e-commerce rebuild with Stripe/Paystack integration
  - Pro Max (₦1.5M+): custom application with ongoing security monitoring
- Clickable link/QR to pejji.com/contact prefilled with the Snapshot ID so the Pejji team can see which report the prospect came from

## 4. Pricing tiers

**Card — ₦15,000 or $10 USD**
- Just the report, no phone call, no follow-up
- Aimed at tight-budget SMEs who want the information only
- Delivered within 5 minutes

**Starter — ₦30,000 or $29 USD** ⭐ flagship
- The Card report PLUS a 30-minute Q&A call with the Securva team to walk through findings
- This is the main product — matches the original Gumroad $29 plan from your memory
- Delivered within 5 minutes, Q&A call booked within 48 hours

**Pro — ₦60,000 or $49 USD**
- Everything in Starter PLUS NDPA compliance add-on (detailed NDPC registration check, privacy policy draft, cookie consent banner starter code)
- PLUS 90-day re-scan (we re-run the report 90 days after original purchase to check if findings were fixed)
- Delivered within 5 minutes, NDPA add-on section added to the same PDF

**Whitelabel — ₦150,000 or $99 USD**
- Everything in Pro PLUS removal of Securva branding (customer uses the report internally as if it came from their own team)
- Adds customer's logo + company name on cover
- For marketing agencies and consultants who resell it
- Delivered within 10 minutes

## 5. Data pipeline

```
Customer pays on Gumroad / Paystack
  ↓
Webhook → Cloudflare Worker or vein Worker
  ↓
Worker validates payment + queues scan job
  ↓
Scan worker on box picks up job from queue
  ↓
  ├── Header check (existing securva-api)
  ├── SSL check (openssl s_client + Python wrapper)
  ├── NDPA scraper (existing Pejji pattern)
  ├── Subdomain enum (subfinder + dnsx on box)
  ├── CVE match (existing nuclei templates)
  └── GitHub org dork (existing github-dork-runner.py)
  ↓
  All outputs saved to /tmp/snapshot-<jobid>/
  ↓
PDF generator reads all outputs + renders using WeasyPrint or Puppeteer
  ↓
PDF saved to /home/babakinzo/snapshots/<jobid>.pdf
  ↓
Email sent to customer with PDF attached + download link
  ↓
Job marked complete in customer DB
```

Each step is a separate Python script. Queue is a simple JSON file in `/var/securva/queue/` polled by a cron or systemd timer every minute. No Redis, no Celery, no overkill infra for the first 100 sales.

## 6. What needs to be built

| Component | Time | Status |
|---|---|---|
| PDF template (HTML+CSS for WeasyPrint) | 4 hours | not started |
| Scan orchestrator Python script | 3 hours | partial (api.securva.net already does headers) |
| NDPA scraper integration | 2 hours | exists in draft form |
| CVE matcher | 3 hours | nuclei + tech stack detection already on box |
| Subfinder + dnsx wrapper | 1 hour | already working on box for other purposes |
| GitHub org dork integration | 1 hour | existing github-dork-runner.py, just scope to one org |
| Gumroad webhook handler | 2 hours | new, needs Cloudflare Worker |
| Paystack webhook handler | 2 hours | new, same pattern |
| Customer email delivery (Resend or Mailgun) | 2 hours | new |
| Customer DB (SQLite is fine for 0-1000 sales) | 1 hour | new |
| Landing page on securva.net/snapshot | 3 hours | new, matches existing securva.net CSS |
| Sample report (anonymized, for sales use) | 2 hours | new, needed before first public sale |

**Total build time: ~26 hours.** Realistic timeline: 1 week of part-time focus OR 3 days full-time.

## 7. Launch plan

**Day 0 (today, if approved):** Kingsley greenlights the spec.

**Day 1-3:** I build PDF template, scan orchestrator, and integrate all the existing pipelines. Everything in a new repo `securva-snapshot` with CI/CD and PR workflow per your existing rules.

**Day 4:** Build Gumroad + Paystack webhook handlers. Customer DB. Email delivery.

**Day 5:** Build landing page at `securva.net/snapshot` with pricing table + FAQ + sample report download. Wire "Get Snapshot" button to payment flow.

**Day 6:** End-to-end test with a test payment + test domain.

**Day 7:** Soft launch — announce to:
- Your existing Telegram channels
- Pejji Outreach Notion list
- One LinkedIn post
- One TechCabal Slack post
- One Nairaland thread

**Day 8-14:** Iterate based on first feedback, fix the 3-5 things that break in real usage.

**Week 3-4:** First 10 paying customers, collect feedback, tune the report content.

**Week 5+:** Content marketing pipeline kicks in — each Securva blog post ends with "Want the full version of this analysis for your own site? ₦30K and 5 minutes — https://securva.net/snapshot".

## 8. Revenue targets

**Conservative (realistic for 90-day window):**
- Month 1: 10 sales × ₦30K = ₦300K
- Month 2: 30 sales × ₦30K = ₦900K
- Month 3: 60 sales × ₦30K = ₦1.8M
- 90-day total: ₦3M ≈ 75% of the 90-day revenue target

**Plus the Pejji funnel conversion:**
- Assume 10% of Snapshot buyers upsell to a Pejji package
- Average Pejji package value: ₦200K (weighted across Card/Starter/Growth)
- Month 1-3 funnel revenue: 10 × ₦200K = ₦2M extra on top of Snapshot direct revenue

**Combined 90-day potential: ~₦5M.** Hits the 90-day revenue target on this product alone. Any other play (fintech due diligence, continuous monitoring, etc.) is pure upside.

## 9. What this does NOT do (scope guardrails)

- NOT a full penetration test. No exploitation, no active CVE confirmation beyond passive detection.
- NOT a compliance certification. The NDPA check is a signal, not a legal opinion.
- NOT ongoing monitoring. One-shot scan only. Continuous monitoring is a separate product (Play 3 in the revenue brainstorm).
- NOT a replacement for hiring a CISO. For that you go through Pejji or a dedicated agency.
- NOT authorized testing for third-party bounty submission. The scanner runs passively and never probes beyond what the user can do with a browser.

These guardrails protect us legally AND position the product honestly so customers do not expect more than they get.

## 10. Legal + ethical notes

- Every Snapshot runs ONLY against the domain the customer provides.
- Terms of service include a checkbox: "I own or have authorization to scan this domain."
- Refund policy: 100% refund within 24 hours if the customer is unhappy with the report quality.
- Data retention: customer domains + PDF reports kept for 90 days then deleted automatically.
- NDPA compliance on our side: we are a data controller for customer email addresses, we store them in a simple DB with a privacy notice linked from securva.net/snapshot.

## 11. Open questions for Kingsley

1. **Gumroad vs Paystack as primary payment rail?** Gumroad is easier to set up globally but charges higher fees. Paystack is Nigerian-native with lower fees but less international reach. My instinct: Paystack for ₦ pricing + Gumroad for USD pricing, both enabled.

2. **Do you want the PDF generated via WeasyPrint (Python, fast, no external service) or Puppeteer (more visual control, needs headless Chrome)?** WeasyPrint is cheaper to run. Puppeteer makes prettier reports.

3. **Sample domain for the public sample report?** We need ONE anonymized example to show prospects before purchase. I can use a generic .com with the scan output fuzzed, or use blessedops.com / pejji.com as real examples.

4. **Branding: Securva brand only, or Securva + BlessedOps co-branded?** v2 roadmap says Red Hat model (HeaderGuard open source + Securva paid). I would keep it Securva-branded with a small "Part of the BlessedOps Group" footnote.

5. **Should the NDPA compliance add-on in the Pro tier be a separate 4-page section, or integrated throughout the report?** My recommendation: separate appendix because it is value-add not core, and it is easier to sell as a distinct differentiator.

6. **Launch timing.** Day 0 = today if approved. Day 7 soft launch = Day 12 of the 90-day challenge. Want to push faster by dropping some features (no Whitelabel tier, no 90-day re-scan) to go live by Day 3? Your call.

## 12. Next concrete action if you approve

I can start today by creating a new private repo `Pejji-ng/securva-snapshot`, setting up the Astro project scaffold matching securva.net's existing visual language, and drafting the PDF template + sample report. Everything in branches and PRs per your existing rules. No live deployment without your approval on every merge.

Wait for your greenlight before touching any code. Spec is ready.
