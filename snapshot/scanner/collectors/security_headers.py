"""
Security headers collector — calls api.securva.net/api/scan for the existing
header audit stack (HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
Referrer-Policy, Permissions-Policy).

The api.securva.net backend already does this. We just wrap its response into
our JSON schema shape.

Returns:
  {
    "status": "ok" | "failed",
    "grade": "A".."F",
    "score": int,
    "headers": [
       {"name": str, "status": "pass"|"fail"|"warn", "value": str, "note": str},
       ...
    ],
    "raw_api_response": dict  # for debugging
  }
"""
import json
import urllib.request
import urllib.error

API_URL = "https://api.securva.net/api/scan"
TIMEOUT = 30

# The 6 headers the Securva API currently returns + 4 more we compute ourselves later.
CANONICAL_HEADERS = [
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
]

HEADER_NOTES = {
    "strict-transport-security": "Forces browsers to use HTTPS. Protects against downgrade attacks.",
    "content-security-policy": "Restricts which scripts, styles, and resources can load. Best defense against XSS.",
    "x-frame-options": "Prevents the page from being embedded in iframes. Blocks clickjacking.",
    "x-content-type-options": "Tells browsers to respect declared Content-Type. Prevents MIME sniffing attacks.",
    "referrer-policy": "Controls what info gets leaked in the Referer header when users click outbound links.",
    "permissions-policy": "Restricts which browser features (camera, mic, geo) the page can use.",
}


def _fetch_api(domain: str) -> dict:
    url = f"{API_URL}?domain={urllib.parse.quote(domain)}"
    req = urllib.request.Request(url, headers={"User-Agent": "securva-snapshot/0.2"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def collect(domain: str, box_ssh: str | None = None) -> dict:
    try:
        raw = _fetch_api(domain)
    except urllib.error.HTTPError as e:
        return {"status": "failed", "error": f"api returned {e.code}", "grade": "F", "score": 0, "headers": []}
    except Exception as e:
        return {"status": "failed", "error": str(e), "grade": "F", "score": 0, "headers": []}

    # api.securva.net response shape: {"domain", "grade", "score", "headers": [{header, status, value}]}
    headers_out = []
    for h in raw.get("headers", []):
        name = h.get("header", "").lower()
        headers_out.append({
            "name": name,
            "display_name": name.upper().replace("-", "-"),
            "status": h.get("status", "fail"),
            "value": h.get("value", ""),
            "note": HEADER_NOTES.get(name, ""),
        })

    return {
        "status": "ok",
        "grade": raw.get("grade", "F"),
        "score": raw.get("score", 0),
        "headers": headers_out,
        "raw_api_response": raw,
    }
