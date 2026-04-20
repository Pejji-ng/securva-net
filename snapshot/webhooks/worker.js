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
 *
 * Phase 4.1: Box no longer uploads to R2. Box returns PDF bytes base64-encoded
 * in the scan response; Worker writes to R2 via the native BUCKET binding and
 * serves downloads through /api/pdf/:token. Eliminates the R2 S3-API
 * dependency (and its TLS provisioning quirks) + removes R2 credentials from
 * the box.
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
      if (pathname === '/api/intake' && request.method === 'POST') {
        return await handleIntake(request, env);
      }
      if (pathname === '/api/intake' && request.method === 'OPTIONS') {
        return corsResponse();
      }
      if (pathname.startsWith('/api/job/') && pathname.endsWith('/status') && request.method === 'GET') {
        const jobId = pathname.split('/')[3];
        return await handleJobStatus(jobId, env);
      }
      if (pathname.startsWith('/api/pdf/') && request.method === 'GET') {
        const token = pathname.slice('/api/pdf/'.length);
        return await handlePdfDownload(token, env);
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

  // Parse form-encoded payload (Gumroad uses x-www-form-urlencoded)
  const params = new URLSearchParams(body);

  // Gumroad classic Ping does NOT include HMAC signature on payloads.
  // Validate instead by matching seller_id (which Gumroad embeds in every Ping)
  // against our known account's seller_id. This prevents someone else's
  // Gumroad account from spoofing webhooks to our endpoint.
  const sellerId = params.get('seller_id');
  if (!sellerId || sellerId !== env.GUMROAD_SELLER_ID) {
    return jsonResponse({ error: 'invalid seller' }, 401);
  }

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
// Custom intake endpoint — called from securva.net/snapshot/intake
// Same purpose as Tally webhook but for our own form. No signature
// verification needed since we control both sides. CORS restricted
// to securva.net origin.
// ============================================================

const ALLOWED_ORIGINS = new Set([
  'https://securva.net',
  'https://www.securva.net',
]);

function corsHeaders(origin) {
  const allowed = origin && ALLOWED_ORIGINS.has(origin) ? origin : 'https://securva.net';
  return {
    'Access-Control-Allow-Origin': allowed,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function corsResponse() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

async function handleIntake(request, env) {
  const origin = request.headers.get('Origin');
  const cors = corsHeaders(origin);

  if (origin && !ALLOWED_ORIGINS.has(origin)) {
    return new Response(JSON.stringify({ error: 'forbidden origin' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  let payload;
  try {
    payload = await request.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: 'invalid json' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  const orderRef = payload.order_ref;
  const submittedUrl = payload.url;

  if (!orderRef || !submittedUrl) {
    return new Response(JSON.stringify({ error: 'missing order_ref or url' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  // Normalize URL
  let cleanUrl = String(submittedUrl).trim();
  if (!cleanUrl.match(/^https?:\/\//)) {
    cleanUrl = 'https://' + cleanUrl;
  }
  try {
    new URL(cleanUrl);
  } catch (e) {
    return new Response(JSON.stringify({ error: 'invalid url' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  // Look up the job
  const job = await env.DB.prepare(
    `SELECT id, status FROM jobs WHERE order_id = ? LIMIT 1`
  ).bind(orderRef).first();

  if (!job) {
    return new Response(JSON.stringify({ error: 'order not found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  if (job.status !== 'awaiting_url') {
    return new Response(JSON.stringify({ error: 'already submitted', status: job.status }), {
      status: 409,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  const now = Date.now();
  await env.DB.prepare(
    `UPDATE jobs SET url = ?, status = 'queued', updated_at = ? WHERE order_id = ? AND status = 'awaiting_url'`
  ).bind(cleanUrl, now, orderRef).run();

  return new Response(JSON.stringify({ status: 'ok' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json', ...cors },
  });
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

    // Phase 4.1: box returns base64 PDF bytes; Worker writes to R2 via native
    // binding (avoids the R2 S3-API TLS endpoint entirely and keeps R2
    // credentials out of the box).
    if (!scanData.pdf_base64) {
      throw new Error('Box response missing pdf_base64');
    }
    const pdfBytes = Uint8Array.from(atob(scanData.pdf_base64), c => c.charCodeAt(0));
    const r2Key = `snapshots/${job.id}.pdf`;
    await env.BUCKET.put(r2Key, pdfBytes, {
      httpMetadata: { contentType: 'application/pdf' },
      customMetadata: { jobId: job.id, tier: job.tier, domain: new URL(job.url).hostname },
    });

    // Opaque download token. Stored alongside the R2 key so the public URL
    // has no predictable relationship to job_id (can't enumerate).
    const downloadToken = crypto.randomUUID().replace(/-/g, '') + crypto.randomUUID().replace(/-/g, '').slice(0, 16);
    const pdfUrl = `https://snap.securva.net/api/pdf/${downloadToken}`;

    const grade = scanData.scan_json?.sections?.executive_summary?.grade || 'N/A';
    const topRecommendations = (scanData.scan_json?.sections?.remediation?.top_3 || [])
      .map(r => `- ${r}`).join('\n') || '- (see full report)';

    // Mark done
    await env.DB.prepare(
      `UPDATE jobs
       SET status = 'done', pdf_url = ?, pdf_r2_key = ?, download_token = ?,
           scan_json = ?, completed_at = ?, updated_at = ?
       WHERE id = ?`
    ).bind(pdfUrl, r2Key, downloadToken, JSON.stringify(scanData.scan_json), Date.now(), Date.now(), job.id).run();

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
// PDF download (Worker-served, replaces R2 presigned URL pattern)
// ============================================================

const PDF_TTL_MS = 14 * 24 * 60 * 60 * 1000; // 14 days

async function handlePdfDownload(token, env) {
  if (!token || !/^[a-f0-9]{48}$/i.test(token)) {
    return new Response('Not found', { status: 404 });
  }

  const job = await env.DB.prepare(
    `SELECT pdf_r2_key, completed_at, url FROM jobs
     WHERE download_token = ? AND status = 'done'`
  ).bind(token).first();

  if (!job || !job.pdf_r2_key) {
    return new Response('Not found', { status: 404 });
  }

  if (Date.now() - job.completed_at > PDF_TTL_MS) {
    return new Response('Link expired. Contact hello@securva.net.', { status: 410 });
  }

  const obj = await env.BUCKET.get(job.pdf_r2_key);
  if (!obj) {
    return new Response('Report not found', { status: 404 });
  }

  const hostname = (() => {
    try { return new URL(job.url).hostname.replace(/[^a-z0-9.-]/gi, ''); }
    catch { return 'report'; }
  })();

  return new Response(obj.body, {
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `inline; filename="securva-snapshot-${hostname}.pdf"`,
      'Cache-Control': 'private, max-age=300',
      'X-Content-Type-Options': 'nosniff',
    },
  });
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
  const intakeUrl = `https://securva.net/snapshot/intake?order_ref=${encodeURIComponent(orderId)}`;
  const html = `
<p>Hi,</p>
<p>Thanks for purchasing the Securva Snapshot (${tier} tier, ${price}).</p>
<p>To kick off your audit, please submit your website URL via this link:</p>
<p><a href="${intakeUrl}">${intakeUrl}</a></p>
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
