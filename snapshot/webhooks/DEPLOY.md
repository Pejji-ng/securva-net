# Securva Snapshot — Phase 4 Deploy Runbook

Step-by-step deployment of the Phase 4 payment + fulfillment pipeline. Ordered by dependency. Each step has a clear success check.

## Prerequisites

- Cloudflare account with securva.net zone active
- Wrangler CLI installed locally (`npm i -g wrangler`)
- Python 3.10+ on the research box
- SSH access to the box (babakinzo@securva-box)
- Resend.com account (free tier OK to start)
- (no Tally needed — custom intake form at securva.net/snapshot/intake auto-deploys via CF Pages)
- Gumroad seller account

---

## Step 1 — Cloudflare resources (Kingsley desk, 15 min)

### 1a. Create D1 database
```bash
cd /path/to/securva-net/snapshot/webhooks
wrangler d1 create securva-snapshot
# → copy the database_id from output into wrangler.toml
```

Apply schema:
```bash
wrangler d1 execute securva-snapshot --file=./schema.sql
```

Verify:
```bash
wrangler d1 execute securva-snapshot --command="SELECT name FROM sqlite_master WHERE type='table';"
# Expect: jobs, jobs_last_hour (view)
```

### 1b. Create R2 bucket
```bash
wrangler r2 bucket create securva-snapshots
```

Verify:
```bash
wrangler r2 bucket list
```

### 1c. Create KV namespace for locks
```bash
wrangler kv:namespace create snapshot-locks
# → copy the id into wrangler.toml [[kv_namespaces]] section
```

### 1d. Generate R2 access credentials (for the box)
In Cloudflare dashboard → R2 → Manage R2 API Tokens → Create API Token
- Name: `securva-box-r2`
- Permissions: Object Read & Write
- Scope: `securva-snapshots` bucket only
- Save the `accessKeyId` + `secretAccessKey` for Step 3

---

## Step 2 — Intake form (no manual setup needed)

The customer intake form is a custom page at `securva.net/snapshot/intake`. It ships with this repo as `snapshot/intake.html` and auto-deploys via CF Pages when merged to main. When the Gumroad webhook fires, the Worker emails the customer a link like `https://securva.net/snapshot/intake?order_ref=ABC123`. The customer enters their URL, form POSTs directly to `https://snap.securva.net/api/intake`, Worker validates and queues the job.

No Tally, no third-party dependency, no webhook signature to verify. Form is branded + matches securva.net aesthetic.

Verify after merge to main:
```bash
curl -sI https://securva.net/snapshot/intake
# Expect: HTTP 200 after CF Pages deploys (~60s)
```

---

## Step 3 — Resend email setup (Kingsley desk, 10 min)

1. Sign up at resend.com (free tier: 100 emails/day, 3K/month)
2. Add + verify domain `securva.net` — follow Resend's DNS wizard (3 SPF/DKIM records to add to Cloudflare DNS)
3. Create API key with scope `send:*@securva.net` — save as `RESEND_API_KEY`

Wait for the domain to verify (usually <5 min after DNS records propagate).

Test send:
```bash
curl -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer $RESEND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"from":"Securva <snapshot@securva.net>","to":["you@example.com"],"subject":"test","html":"<p>works</p>"}'
```

---

## Step 4 — Box-side scanner API (Baba, 3 hours)

On the research box (babakinzo@165.232.109.143):

### 4a. Install dependencies
```bash
cd /opt/securva-snapshot  # create if missing
git clone https://github.com/Pejji-ng/securva-net .
cd snapshot/scanner

python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn jinja2 weasyprint boto3 pydantic
# Plus whatever the collectors need (requests, urllib3, etc.)
```

### 4b. Create environment file
```bash
sudo mkdir -p /etc/securva
sudo tee /etc/securva/snapshot-api.env > /dev/null <<'EOF'
BOX_API_TOKEN=REPLACE_WITH_SECURE_RANDOM_64_CHARS
R2_ACCOUNT_ID=YOUR_CF_ACCOUNT_ID
R2_ACCESS_KEY_ID=FROM_STEP_1d
R2_SECRET_ACCESS_KEY=FROM_STEP_1d
R2_BUCKET=securva-snapshots
EOF
sudo chmod 600 /etc/securva/snapshot-api.env
sudo chown root:root /etc/securva/snapshot-api.env
```

Generate `BOX_API_TOKEN`:
```bash
openssl rand -base64 48 | tr '+/' '-_' | tr -d '='
```

### 4c. Systemd service
```bash
sudo tee /etc/systemd/system/securva-snapshot-api.service > /dev/null <<'EOF'
[Unit]
Description=Securva Snapshot Scanner API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=babakinzo
Group=babakinzo
WorkingDirectory=/opt/securva-snapshot/snapshot/scanner
EnvironmentFile=/etc/securva/snapshot-api.env
ExecStart=/opt/securva-snapshot/snapshot/scanner/.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8089
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now securva-snapshot-api
sudo systemctl status securva-snapshot-api  # expect: active (running)
```

### 4d. nginx reverse proxy with Cloudflare IP allowlist
```bash
sudo tee /etc/nginx/conf.d/snapshot-api.conf > /dev/null <<'EOF'
# Cloudflare IP ranges (keep up-to-date from https://www.cloudflare.com/ips/)
geo $is_cloudflare {
    default 0;
    173.245.48.0/20   1;
    103.21.244.0/22   1;
    103.22.200.0/22   1;
    103.31.4.0/22     1;
    141.101.64.0/18   1;
    108.162.192.0/18  1;
    190.93.240.0/20   1;
    188.114.96.0/20   1;
    197.234.240.0/22  1;
    198.41.128.0/17   1;
    162.158.0.0/15    1;
    104.16.0.0/13     1;
    104.24.0.0/14     1;
    172.64.0.0/13     1;
    131.0.72.0/22     1;
    # plus your own office/home IP for testing
    YOUR_IP_HERE/32   1;
}

server {
    listen 443 ssl http2;
    server_name scanner.internal.securva.net;

    # ssl_certificate + ssl_certificate_key here (Let's Encrypt)

    location / {
        if ($is_cloudflare = 0) {
            return 403;
        }
        proxy_pass http://127.0.0.1:8089;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 90s;
    }
}
EOF

sudo nginx -t
sudo systemctl reload nginx
```

Add 2 DNS records in Cloudflare:

**scanner.internal** (for box API, already created):
- Type: A, Name: `scanner.internal`, Value: `165.232.109.143` (box IP)
- Proxy: DNS-only (gray cloud) — we want the Worker to hit the box directly, not through another CF layer

**snap** (for Worker route, NEW):
- Type: CNAME, Name: `snap`, Target: `securva.net`
- Proxy: **Proxied (orange cloud)** — required for Worker route to intercept requests
- Without this record, the Worker route in wrangler.toml cannot attach

### 4e. Smoke test
```bash
curl -X POST https://scanner.internal.securva.net/scan-and-render \
  -H "Authorization: Bearer $BOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain":"babakizo.com","tier":"Starter","job_id":"test-001"}'
# Expect: 200 OK with pdf_url + scan_json + runtime_ms
```

Save for Step 5:
- `BOX_SCANNER_ENDPOINT` = `https://scanner.internal.securva.net/scan-and-render`
- `BOX_API_TOKEN` = (the one you generated above)

---

## Step 5 — Deploy the Cloudflare Worker (Baba, 1 hour)

### 5a. Fill in wrangler.toml
Replace `FILL_IN_AFTER_CREATE` placeholders with the IDs from Step 1.

### 5b. Set secrets
```bash
cd snapshot/webhooks
wrangler secret put GUMROAD_SELLER_ID
wrangler secret put RESEND_API_KEY
wrangler secret put BOX_SCANNER_ENDPOINT
wrangler secret put BOX_API_TOKEN
# Optional for Phase 4.1:
wrangler secret put PAYSTACK_SECRET_KEY
```

Note on Gumroad auth: classic Ping webhooks do NOT support HMAC signatures. Instead we verify the `seller_id` field embedded in every Ping payload matches our known account. Get your seller_id from Gumroad → Settings → Advanced (shown below the Ping endpoint field).

### 5c. Deploy
```bash
wrangler deploy
# Worker is now live at snap.securva.net/api/*
```

### 5d. Verify
```bash
curl https://snap.securva.net/api/health
# Expect: 200 OK with {"status":"ok","last_hour_by_status":[], ...}
```

---

## Step 6 — Gumroad products (Kingsley desk, 30 min)

1. Log into Gumroad
2. Unpublish + delete the old CAD$97 / USD$97 duplicate products (per the gumroad_launch_package tasks)
3. Create 4 new products with these exact permalink slugs (the Worker code matches on them):

| Product Name | Permalink | Price | Tier field in Worker |
|---|---|---|---|
| Securva Snapshot — Card | `securva-snapshot-card` | $10 USD | Card |
| Securva Snapshot — Starter | `securva-snapshot-starter` | $29 USD | Starter |
| Securva Snapshot — Pro | `securva-snapshot-pro` | $49 USD | Pro |
| Securva Snapshot — Whitelabel | `securva-snapshot-whitelabel` | $99 USD | Whitelabel |

For each product:
- Upload the sample PDF as the deliverable (customers get the actual PDF later via email; Gumroad's default download is the sample/teaser)
- Gumroad account-level Ping: Settings → Advanced → Ping endpoint: paste `https://snap.securva.net/api/gumroad-webhook` → save. Also copy the `seller_id` shown below the endpoint field - that's what we use for webhook authentication (classic Ping has no HMAC signature).
- Use the description from `gumroad_launch_package_v1.md` Block 2/3 (updated to match the actual automated product)

---

## Step 7 — End-to-end dry run (Baba + Kingsley, 30 min)

### 7a. Self-purchase on Gumroad
- Use a test email you control
- Buy the Starter tier ($29)
- Immediately check: email received with intake form link (securva.net/snapshot/intake?order_ref=...)
- Open the link, submit `babakizo.com` in the form
- Wait 5–10 min
- Second email arrives with PDF link?
- Download PDF, verify it renders as expected

### 7b. Check D1
```bash
wrangler d1 execute securva-snapshot --command="SELECT id, status, url, email, completed_at FROM jobs ORDER BY created_at DESC LIMIT 10;"
```

### 7c. Check R2
```bash
wrangler r2 object list securva-snapshots --limit 10
```

### 7d. Refund yourself on Gumroad
Don't forget, so you can repeat the test cleanly.

---

## Step 8 — Go live (Kingsley, 30 min)

Once Step 7 passes cleanly:
1. Update securva.net/snapshot landing page to point buy buttons at the live Gumroad product URLs
2. Post Sterling Wave 3 blog (already drafted) linking to securva.net/snapshot
3. Soft-announce on X/LinkedIn
4. Monitor D1 for incoming jobs + failures over the next 48h

---

## Troubleshooting

| Symptom | Diagnosis | Fix |
|---|---|---|
| Gumroad webhook returns 401 | Wrong seller_id | Re-check `wrangler secret put GUMROAD_SELLER_ID` matches the seller_id shown in Gumroad Settings → Advanced |
| Tally webhook returns 401 | Wrong signing secret or wrong field key names | Match field keys to `website_url` + `order_ref` or update worker.js field lookup |
| Box API returns 401 | Token mismatch | Check `/etc/securva/snapshot-api.env` matches `wrangler secret get BOX_API_TOKEN` |
| Box API returns 403 from nginx | IP not allowlisted | Add your test IP to `/etc/nginx/conf.d/snapshot-api.conf` `geo` block |
| Resend returns 403 | Domain not verified | Re-check Resend dashboard DNS verification |
| Jobs stuck in `queued` | Cron not firing | `wrangler tail` to see Worker logs; confirm `[triggers] crons` in wrangler.toml |
| PDF rendering slow (>30s) | WeasyPrint font loading | Pre-cache fonts on the box, restart systemd service |

---

## Observability

- Worker logs: `wrangler tail` (real-time)
- Box scanner logs: `sudo journalctl -u securva-snapshot-api -f`
- D1 job history: `wrangler d1 execute securva-snapshot --command="SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100;"`
- R2 metrics: Cloudflare dashboard → R2 → securva-snapshots → Metrics
- Email delivery: Resend dashboard → Logs

---

## Rollback

If something breaks after launch:
- Pause Gumroad products: set them to "hidden" in Gumroad dashboard (stops new sales immediately)
- Pause CF Worker: `wrangler deployments list` → `wrangler rollback <deployment-id>`
- Pause box API: `sudo systemctl stop securva-snapshot-api`
- Refund any in-flight customers: `wrangler d1 execute securva-snapshot --command="SELECT email, order_id FROM jobs WHERE status IN ('queued','running');"`
