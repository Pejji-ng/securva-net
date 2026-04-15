# Payment webhooks (Phase 4)

This directory will contain the Cloudflare Workers that handle payment provider callbacks.

Planned files (Phase 4):
- `gumroad-webhook.js` — Cloudflare Worker for Gumroad sale events ($29 USD flow)
- `paystack-webhook.js` — Cloudflare Worker for Paystack charge success (₦30K NGN flow)
- `deploy-notes.md` — step-by-step deployment instructions for Kingsley

Each webhook:
- Validates the incoming payload signature against the stored secret
- Parses customer email + purchased tier + payment reference
- Writes a new job record to the customer DB on the box
- Sends a confirmation email acknowledging the payment
- Returns 200 to the provider so they do not retry

Secrets (installed via secure stdin pattern by Kingsley in Phase 4):
- `GUMROAD_WEBHOOK_SECRET` — signs Gumroad payloads
- `PAYSTACK_SECRET_KEY` — Kingsley's Paystack live secret
- `RESEND_API_KEY` (or Mailgun equivalent) — for outbound email
- `BOX_API_TOKEN` — auth for the box to accept queue writes from the Workers

Phase 4 trigger: Phase 3 merge (PDF rendering engine working).
