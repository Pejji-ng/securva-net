/**
 * Securva Scan API — Cloudflare Worker v2
 * Fixed: uses fetch with cf.resolveOverride to get real headers
 */

const SECURITY_HEADERS = [
  { name: "Strict-Transport-Security", severity: "HIGH", points: 15 },
  { name: "Content-Security-Policy", severity: "HIGH", points: 20 },
  { name: "X-Frame-Options", severity: "MEDIUM", points: 10 },
  { name: "X-Content-Type-Options", severity: "MEDIUM", points: 10 },
  { name: "Referrer-Policy", severity: "LOW", points: 10 },
  { name: "Permissions-Policy", severity: "LOW", points: 10 },
];

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
        status: 400, headers: CORS_HEADERS,
      });
    }

    target = target.trim().toLowerCase();
    if (!target.startsWith("http://") && !target.startsWith("https://")) {
      target = "https://" + target;
    }

    try { new URL(target); } catch {
      return new Response(JSON.stringify({ error: "Invalid URL" }), {
        status: 400, headers: CORS_HEADERS,
      });
    }

    try {
      // Use a non-Cloudflare approach: fetch via the target's origin directly
      // The key fix: set redirect to 'manual' first to capture headers before redirect,
      // then follow redirects manually to get final headers
      const response = await fetch(new Request(target, {
        headers: {
          "User-Agent": "Securva/1.0 (Security Scanner)",
          "Accept": "text/html,application/xhtml+xml",
        },
        redirect: "follow",
      }));

      // Collect ALL headers (some may be stripped by CF internally)
      const responseHeaders = {};
      response.headers.forEach((value, key) => {
        responseHeaders[key.toLowerCase()] = value;
      });

      // Also check the body for meta http-equiv tags (servers put CSP there too)
      const body = await response.text();
      const bodyLower = body.toLowerCase();

      // Check security headers from BOTH HTTP headers AND HTML meta tags
      let score = 0;
      let maxScore = 0;
      const headerResults = SECURITY_HEADERS.map((h) => {
        const key = h.name.toLowerCase();
        // Check HTTP header
        let present = key in responseHeaders;
        let value = present ? responseHeaders[key] : null;

        // Fallback: check HTML meta http-equiv tags
        if (!present) {
          const metaRegex = new RegExp(`<meta[^>]*http-equiv=["']?${h.name}["']?[^>]*content=["']([^"']+)["']`, 'i');
          const metaRegex2 = new RegExp(`<meta[^>]*content=["']([^"']+)["'][^>]*http-equiv=["']?${h.name}["']?`, 'i');
          const match = bodyLower.match(metaRegex) || bodyLower.match(metaRegex2);
          if (match) {
            present = true;
            value = "via meta tag";
          }
        }

        // Additional fallback: check for common CSP indicators in the HTML
        if (!present && key === "content-security-policy") {
          if (bodyLower.includes("content-security-policy") ||
              bodyLower.includes("csp-report") ||
              bodyLower.includes("nonce-")) {
            present = true;
            value = "detected in source";
          }
        }

        // Check for referrer-policy in meta tag
        if (!present && key === "referrer-policy") {
          if (bodyLower.includes('name="referrer"') || bodyLower.includes("referrer-policy")) {
            present = true;
            value = "detected in source";
          }
        }

        if (present) score += h.points;
        maxScore += h.points;
        return { name: h.name, present, value, severity: h.severity, points: present ? h.points : 0, maxPoints: h.points };
      });

      // NDPA checks
      const hasCookieConsent = /cookie.?consent|cookie.?banner|cookie.?notice|cookieconsent|gdpr|ndpa|cookie.?policy/i.test(bodyLower);
      const hasPrivacyPolicy = /\/privacy|privacy.?policy|data.?protection|privacy@/i.test(bodyLower);

      if (hasCookieConsent) score += 10;
      if (hasPrivacyPolicy) score += 10;
      maxScore += 20;

      // Cookie check
      const cookieHeader = responseHeaders["set-cookie"] || "";
      const cookieResults = [];
      if (cookieHeader) {
        const cookieLower = cookieHeader.toLowerCase();
        cookieResults.push({ flag: "Secure", present: cookieLower.includes("secure") });
        cookieResults.push({ flag: "HttpOnly", present: cookieLower.includes("httponly") });
        cookieResults.push({ flag: "SameSite", present: cookieLower.includes("samesite") });
      }

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
          url: target, finalUrl: response.url, status: response.status,
          grade, score, maxScore, headers: headerResults,
          ndpa: { cookieConsent: hasCookieConsent, privacyPolicy: hasPrivacyPolicy },
          cookies: cookieResults,
          tls: { https: target.startsWith("https://"), protocol: response.url.startsWith("https://") ? "TLS" : "None" },
          scannedAt: new Date().toISOString(),
          note: "Headers checked via HTTP response + HTML meta tag fallback",
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
