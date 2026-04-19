/**
 * Securva Snapshot — Payment + Fulfillment Worker
 *
 * Cloudflare Worker that handles the full automated Snapshot lifecycle:
 *   1. Gumroad / Paystack webhook → create job, email customer the intake form
 *   2. Tally webhook → attach URL to job, mark status=queued
 *   3. Cron trigger → pick up queued jobs, call box scanner, store PDF in R2, email customer
 *   4. GET /api/job/:id/status → allow customer to poll their job
 *   5. GET /api/health → uptime monitor
 *
 * See snapshot/webhooks/DEPLOY.md for step-by-step deployment.
 *
 * Environment bindings (set via wrangler or dashboard):
 *   - DB: D1 database with snapshot/webhooks/schema.sql applied
 *   - BUCKET: R2 bucket named "securva-snapshots"
 *   - LOCKS: KV namespace for idempotency + rate limiting
 *
 * Secrets (set via `wrangler secret put <name>`):
 *   - GUMROAD_WEBHOOK_SECRET
 *   - PAYSTACK_SECRET_KEY (optional, for Phase 4.1)
 *   - TALLY_WEBHOOK_SECRET
 *   - RESEND_API_KEY
 *   - BOX_SCANNER_ENDPOINT (e.g. https://scanner.internal.securva.net/scan-and-render)
 *   - BOX_API_TOKEN
 *   - TALLY_FORM_URL (base URL of the intake Tally form)
 */

const PRICING = {
  'securva-snapshot-card': { tier: 'Card', priceUSD: 10, priceNGN: 15000 },
  'securva-snapshot-starter': { tier: 'Starter', priceUSD: 29, priceNGN: 30000 },
  'securva-snapshot-pro': { tier: 'Pro', priceUSD: 49, priceNGN: 60000 },
  'securva-snapshot-whitelabel': { tier: 'Whitelabel', priceUSD: 99, priceNGN: 150000 },
};

const RESEND_API = 'https://api.resend.com/emails';
const FROM_ADDRESS = 'Securva <snapshot@securva.net>';

// ============================================================
// Router
// ============================================================

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const { pathname } = url;

    try {
      if (pathname === '/api/gumroad-webhook' && request.method === 'POST') {
        return await handleGumroadWebhook(request, env);
      }
      if (pathname === '/api/paystack-webhook' && request.method === 'POST') {
        return await handlePaystackWebhook(request, env);
      }
      if (pathname === '/api/tally-webhook' && request.method === 'POST') {
        return await handleTallyWebhook(request, env);
      }
      if (pathname.startsWith('/api/job/') && pathname.endsWith('/status') && request.method === 'GET') {
        const jobId = pathname.split('/')[3];
        return await handleJobStatus(jobId, env);
      }
      if (pathname === '/api/health' && request.method === 'GET') {
        return await handleHealth(env);
      }
      return jsonResponse({ error: 'not found' }, 404);
    } catch (err) {
      console.error('Worker error:', err.message, err.stack);
      return jsonResponse({ error: 'internal error' }, 500);
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(pickUpQueuedJobs(env));
  },
};

// ============================================================
// Gumroad webhook
// Docs: https://help.gumroad.com/article/215-response-webhook-ping
// ============================================================

async function handleGumroadWebhook(request, env) {
  const body = await request.text();

  // Gumroad signs the body with HMAC-SHA256 using your webhook secret
  const signature = request.headers.get('X-Gumroad-Signature');
  if (!signature || !(await verifyHmac(body, signature, env.GUMROAD_WEBHOOK_SECRET))) {
    return jsonResponse({ error: 'invalid signature' }, 401);
  }

  // Parse form-encoded payload (Gumroad uses x-www-form-urlencoded)
  const params = new URLSearchParams(body);
  const orderId = params.get('sale_id');
  const email = params.get('email');
  const productSlug = params.get('permalink');  // e.g. 'securva-snapshot-starter'

  if (!orderId || !email || !productSlug) {
    return jsonResponse({ error: 'missing fields' }, 400);
  }

  const pricing = PRICING[productSlug];
  if (!pricing) {
    console.warn('Unknown product slug:', productSlug);
    return jsonResponse({ error: 'unknown product' }, 400);
  }

  // Idempotency: don't process the same order twice
  const lockKey = `gumroad:${orderId}`;
  const existingLock = await env.LOCKS.get(lockKey);
  if (existingLock) {
    return jsonResponse({ status: 'already processed' }, 200);
  }
  await env.LOCKS.put(lockKey, 'processed', { expirationTtl: 60 * 60 * 24 * 30 });  // 30 days

  // Create job record
  const jobId = crypto.randomUUID();
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO jobs (id, order_id, email, tier, status, created_at, updated_at)
     VALUES (?, ?, ?, ?, 'awaiting_url', ?, ?)`
  ).bind(jobId, orderId, email, pricing.tier, now, now).run();

  // Email the customer the Tally form link
  await sendSubmitUrlEmail(env, { email, tier: pricing.tier, price: `$${pricing.priceUSD} USD`, orderId });

  return jsonResponse({ status: 'ok', job_id: jobId }, 200);
}

// ============================================================
// Paystack webhook (Phase 4.1)
// ============================================================

async function handlePaystackWebhook(request, env) {
  const body = await request.text();

  // Paystack uses X-Paystack-Signature with HMAC-SHA512 of the body
  const signature = request.headers.get('X-Paystack-Signature');
  if (!signature || !(await verifyHmac(body, signature, env.PAYSTACK_SECRET_KEY, 'SHA-512'))) {
    return jsonResponse({ error: 'invalid signature' }, 401);
  }

  const payload = JSON.parse(body);
  if (payload.event !== 'charge.success') {
    return jsonResponse({ status: 'ignored' }, 200);
  }

  const orderId = payload.data.reference;
  const email = payload.data.customer.email;
  const productSlug = payload.data.metadata?.product_slug || 'securva-snapshot-starter';

  const pricing = PRICING[productSlug];
  if (!pricing) {
    return jsonResponse({ error: 'unknown product' }, 400);
  }

  // Idempotency
  const lockKey = `paystack:${orderId}`;
  if (await env.LOCKS.get(lockKey)) {
    return jsonResponse({ status: 'already processed' }, 200);
  }
  await env.LOCKS.put(lockKey, 'processed', { expirationTtl: 60 * 60 * 24 * 30 });

  const jobId = crypto.randomUUID();
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO jobs (id, order_id, email, tier, status, created_at, updated_at)
     VALUES (?, ?, ?, ?, 'awaiting_url', ?, ?)`
  ).bind(jobId, orderId, email, pricing.tier, now, now).run();

  await sendSubmitUrlEmail(env, { email, tier: pricing.tier, price: `₦${pricing.priceNGN.toLocaleString()} NGN`, orderId });

  return jsonResponse({ status: 'ok', job_id: jobId }, 200);
}

// ============================================================
// Tally webhook — customer submits their URL
// ============================================================

async function handleTallyWebhook(request, env) {
  const body = await request.text();

  // Tally uses X-Tally-Signature
  const signature = request.headers.get('X-Tally-Signature');
  if (!signature || !(await verifyHmac(body, signature, env.TALLY_WEBHOOK_SECRET))) {
    return jsonResponse({ error: 'invalid signature' }, 401);
  }

  const payload = JSON.parse(body);
  // Tally sends { data: { fields: [...] }, ... }
  const fields = payload?.data?.fields || [];
  const urlField = fields.find(f => f.label?.toLowerCase().includes('url') || f.key === 'website_url');
  const orderRefField = fields.find(f => f.label?.toLowerCase().includes('ref') || f.key === 'order_ref');

  const submittedUrl = urlField?.value;
  const orderRef = orderRefField?.value;

  if (!submittedUrl || !orderRef) {
    return jsonResponse({ error: 'missing url or ref' }, 400);
  }

  // Normalize URL (ensure scheme)
  let cleanUrl = submittedUrl.trim();
  if (!cleanUrl.match(/^https?:\/\//)) {
    cleanUrl = 'https://' + cleanUrl;
  }

  // Update job record
  const now = Date.now();
  const result = await env.DB.prepare(
    `UPDATE jobs
     SET url = ?, status = 'queued', updated_at = ?
     WHERE order_id = ? AND status = 'awaiting_url'`
  ).bind(cleanUrl, now, orderRef).run();

  if (result.meta.changes === 0) {
    return jsonResponse({ error: 'no matching job' }, 404);
  }

  return jsonResponse({ status: 'ok' }, 200);
}

// ============================================================
// Scheduled job pickup
// Cron: every 5 minutes
// ============================================================

async function pickUpQueuedJobs(env) {
  const maxConcurrent = 3;

  // Select up to N queued jobs
  const result = await env.DB.prepare(
    `SELECT id, url, email, tier, order_id FROM jobs
     WHERE status = 'queued'
     ORDER BY created_at ASC
     LIMIT ?`
  ).bind(maxConcurrent).all();

  const jobs = result.results || [];
  if (jobs.length === 0) return;

  // Process in parallel
  await Promise.all(jobs.map(job => processJob(job, env)));
}

async function processJob(job, env) {
  const now = Date.now();

  // Mark running
  await env.DB.prepare(
    `UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?`
  ).bind(now, job.id).run();

  try {
    // Call box scanner API
    const scanResponse = await fetch(env.BOX_SCANNER_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${env.BOX_API_TOKEN}`,
      },
      body: JSON.stringify({
        domain: new URL(job.url).hostname,
        tier: job.tier,
        job_id: job.id,
      }),
      // Cloudflare Workers max subrequest timeout is 30s by default
      signal: AbortSignal.timeout(60_000),
    });

    if (!scanResponse.ok) {
      throw new Error(`Box scanner returned ${scanResponse.status}`);
    }

    const scanData = await scanResponse.json();
    const pdfUrl = scanData.pdf_url;
    const grade = scanData.scan_json?.sections?.executive_summary?.grade || 'N/A';
    const topRecommendations = (scanData.scan_json?.sections?.remediation?.top_3 || [])
      .map(r => `- ${r}`).join('\n') || '- (see full report)';

    // Mark done
    await env.DB.prepare(
      `UPDATE jobs
       SET status = 'done', pdf_url = ?, scan_json = ?, completed_at = ?, updated_at = ?
       WHERE id = ?`
    ).bind(pdfUrl, JSON.stringify(scanData.scan_json), Date.now(), Date.now(), job.id).run();

    // Email customer
    await sendReportReadyEmail(env, {
      email: job.email,
      domain: new URL(job.url).hostname,
      grade,
      pdfUrl,
      topRecommendations,
    });

  } catch (err) {
    console.error(`Job ${job.id} failed:`, err.message);
    await env.DB.prepare(
      `UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?`
    ).bind(err.message, Date.now(), job.id).run();

    // Email customer an apology + refund note
    await sendFailureEmail(env, {
      email: job.email,
      domain: new URL(job.url).hostname,
      orderId: job.order_id,
    });
  }
}

// ============================================================
// Customer-facing job status endpoint (optional, for polling)
// ============================================================

async function handleJobStatus(orderId, env) {
  const result = await env.DB.prepare(
    `SELECT status, url, created_at, completed_at FROM jobs WHERE order_id = ?`
  ).bind(orderId).first();

  if (!result) return jsonResponse({ error: 'not found' }, 404);
  return jsonResponse(result, 200);
}

// ============================================================
// Health check
// ============================================================

async function handleHealth(env) {
  const result = await env.DB.prepare(
    `SELECT status, COUNT(*) as count FROM jobs
     WHERE created_at > ?
     GROUP BY status`
  ).bind(Date.now() - 60 * 60 * 1000).all();

  return jsonResponse({
    status: 'ok',
    last_hour_by_status: result.results || [],
    timestamp: new Date().toISOString(),
  }, 200);
}

// ============================================================
// Email sending (Resend)
// ============================================================

async function sendSubmitUrlEmail(env, { email, tier, price, orderId }) {
  const tallyUrl = `${env.TALLY_FORM_URL}?order_ref=${encodeURIComponent(orderId)}`;
  const html = `
<p>Hi,</p>
<p>Thanks for purchasing the Securva Snapshot (${tier} tier, ${price}).</p>
<p>To kick off your audit, please submit your website URL via this form:</p>
<p><a href="${tallyUrl}">${tallyUrl}</a></p>
<p>Within 24 hours of submitting, you will receive a second email with your PDF report attached.</p>
<p>Questions? Reply to this email directly. A real human (not a bot) reads them.</p>
<p>&mdash; Securva at Pejji Agency</p>
  `.trim();

  return resendSend(env, email, 'Your Securva Snapshot is ready to start - 1 quick step', html);
}

async function sendReportReadyEmail(env, { email, domain, grade, pdfUrl, topRecommendations }) {
  const html = `
<p>Hi,</p>
<p>Your Securva Snapshot audit for <strong>${domain}</strong> is complete.</p>
<p>Overall grade: <strong>${grade}</strong></p>
<p><a href="${pdfUrl}">Download your full report</a> (link expires in 14 days)</p>
<p><strong>Top 3 things to fix first:</strong></p>
<pre>${topRecommendations}</pre>
<p>If you want help implementing the fixes:</p>
<ul>
  <li>Pejji Card tier (&#8358;60K) - we rebuild your site from scratch</li>
  <li>Securva Watch (&#8358;15K/mo) - we monitor for new issues automatically</li>
</ul>
<p>Reply to this email if you have questions about the findings.</p>
<p>&mdash; Securva at Pejji Agency</p>
  `.trim();

  return resendSend(env, email, `Your Securva Snapshot for ${domain} is ready`, html);
}

async function sendFailureEmail(env, { email, domain, orderId }) {
  const html = `
<p>Hi,</p>
<p>We hit an issue running your Securva Snapshot audit for <strong>${domain}</strong>.</p>
<p>We are refunding your purchase (order ${orderId}) automatically within 24 hours.</p>
<p>If you can reply and tell us what URL you submitted + any context, we will troubleshoot and offer to re-run the audit at no cost.</p>
<p>Sorry for the friction.</p>
<p>&mdash; Securva at Pejji Agency</p>
  `.trim();

  return resendSend(env, email, `Issue with your Securva Snapshot for ${domain}`, html);
}

async function resendSend(env, to, subject, html) {
  const response = await fetch(RESEND_API, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: FROM_ADDRESS,
      to: [to],
      subject,
      html,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Resend failed ${response.status}: ${body}`);
  }
  return true;
}

// ============================================================
// Utility helpers
// ============================================================

async function verifyHmac(body, signature, secret, algorithm = 'SHA-256') {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HMAC', hash: algorithm },
    false,
    ['sign']
  );
  const sigBuf = await crypto.subtle.sign('HMAC', key, enc.encode(body));
  const expected = Array.from(new Uint8Array(sigBuf))
    .map(b => b.toString(16).padStart(2, '0')).join('');

  // Compare using constant-time-ish approach
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  return diff === 0;
}

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
