/**
 * Securva Scan API — Cloudflare Worker
 *
 * Deploy: Cloudflare Dashboard > Workers & Pages > Create > Worker
 * Paste this code, deploy, then update WORKER_URL in the Securva frontend.
 *
 * Endpoint: GET /?url=https://example.com
 * Returns: JSON with headers, score, grade
 */

const SECURITY_HEADERS = [
  { name: "Strict-Transport-Security", severity: "HIGH", points: 15 },
  { name: "Content-Security-Policy", severity: "HIGH", points: 20 },
  { name: "X-Frame-Options", severity: "MEDIUM", points: 10 },
  { name: "X-Content-Type-Options", severity: "MEDIUM", points: 10 },
  { name: "Referrer-Policy", severity: "LOW", points: 10 },
  { name: "Permissions-Policy", severity: "LOW", points: 10 },
];

const COOKIE_FLAGS = ["secure", "httponly", "samesite"];

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Content-Type": "application/json",
};

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    let target = url.searchParams.get("url");

    if (!target) {
      return new Response(JSON.stringify({ error: "Missing ?url= parameter" }), {
        status: 400,
        headers: CORS_HEADERS,
      });
    }

    // Clean and validate URL
    target = target.trim().toLowerCase();
    if (!target.startsWith("http://") && !target.startsWith("https://")) {
      target = "https://" + target;
    }

    try {
      new URL(target);
    } catch {
      return new Response(JSON.stringify({ error: "Invalid URL" }), {
        status: 400,
        headers: CORS_HEADERS,
      });
    }

    try {
      const response = await fetch(target, {
        headers: { "User-Agent": "Securva/1.0 (Security Scanner)" },
        redirect: "follow",
        cf: { cacheTtl: 0 },
      });

      const responseHeaders = Object.fromEntries(
        [...response.headers.entries()].map(([k, v]) => [k.toLowerCase(), v])
      );

      // Check security headers
      let score = 0;
      let maxScore = 0;
      const headerResults = SECURITY_HEADERS.map((h) => {
        const key = h.name.toLowerCase();
        const present = key in responseHeaders;
        const value = present ? responseHeaders[key] : null;
        if (present) score += h.points;
        maxScore += h.points;
        return { name: h.name, present, value, severity: h.severity, points: present ? h.points : 0, maxPoints: h.points };
      });

      // Check NDPA: cookie consent + privacy in HTML
      const body = await response.text();
      const bodyLower = body.toLowerCase();

      const hasCookieConsent = /cookie.?consent|cookie.?banner|cookie.?notice|cookieconsent|gdpr|ndpa/i.test(bodyLower);
      const hasPrivacyPolicy = /\/privacy|privacy.?policy|data.?protection/i.test(bodyLower);

      if (hasCookieConsent) score += 10;
      if (hasPrivacyPolicy) score += 10;
      maxScore += 20;

      // Cookie security check
      const setCookies = response.headers.getAll ? response.headers.getAll("set-cookie") : [];
      const cookieHeader = responseHeaders["set-cookie"] || "";
      const cookieResults = [];
      if (cookieHeader) {
        const cookieLower = cookieHeader.toLowerCase();
        cookieResults.push({ flag: "Secure", present: cookieLower.includes("secure") });
        cookieResults.push({ flag: "HttpOnly", present: cookieLower.includes("httponly") });
        cookieResults.push({ flag: "SameSite", present: cookieLower.includes("samesite") });
      }

      // TLS check (if HTTPS)
      const tlsInfo = {
        https: target.startsWith("https://"),
        protocol: response.url.startsWith("https://") ? "TLS" : "None",
      };

      // Grade
      const pct = maxScore > 0 ? (score / maxScore) * 100 : 0;
      let grade;
      if (pct >= 90) grade = "A";
      else if (pct >= 80) grade = "B";
      else if (pct >= 70) grade = "C";
      else if (pct >= 50) grade = "D";
      else grade = "F";

      return new Response(
        JSON.stringify({
          url: target,
          finalUrl: response.url,
          status: response.status,
          grade,
          score,
          maxScore,
          headers: headerResults,
          ndpa: {
            cookieConsent: hasCookieConsent,
            privacyPolicy: hasPrivacyPolicy,
          },
          cookies: cookieResults,
          tls: tlsInfo,
          scannedAt: new Date().toISOString(),
        }),
        { headers: CORS_HEADERS }
      );
    } catch (err) {
      return new Response(
        JSON.stringify({ error: "Could not reach " + target, details: err.message }),
        { status: 502, headers: CORS_HEADERS }
      );
    }
  },
};
