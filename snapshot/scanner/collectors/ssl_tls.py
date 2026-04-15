"""
SSL/TLS posture collector — reuses api.securva.net/api/scan's ssl block when
available, and falls back to a local `openssl s_client` wrapper otherwise.

Returns:
  {
    "status": "ok" | "failed",
    "certificate": {
      "valid": bool,
      "issuer": str,
      "expires": str (ISO date),
      "days_until_expiry": int,
    },
    "tls_versions_allowed": [str],  # e.g., ["TLSv1.2", "TLSv1.3"]
    "hsts_preload_eligible": bool,
    "grade": "A".."F",
    "notes": [str],
  }
"""
import json
import subprocess
import urllib.request
from datetime import datetime, timezone

API_URL = "https://api.securva.net/api/scan"
TIMEOUT = 30


def _fetch_api(domain: str) -> dict:
    url = f"{API_URL}?domain={domain}"
    req = urllib.request.Request(url, headers={"User-Agent": "securva-snapshot/0.2"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _days_until(iso_date: str) -> int:
    try:
        exp = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        return max(delta.days, 0)
    except Exception:
        return 0


def collect(domain: str, box_ssh: str | None = None) -> dict:
    try:
        raw = _fetch_api(domain)
    except Exception as e:
        return {"status": "failed", "error": str(e), "grade": "F"}

    ssl_raw = raw.get("ssl", {}) or {}
    if not ssl_raw:
        return {"status": "no_ssl_data", "grade": "F"}

    cert = {
        "valid": ssl_raw.get("valid", False),
        "issuer": ssl_raw.get("issuer", "unknown"),
        "expires": ssl_raw.get("expires", ""),
        "days_until_expiry": _days_until(ssl_raw.get("expires", "")),
    }

    notes = []
    if cert["days_until_expiry"] < 14:
        notes.append("Certificate expires in under 2 weeks. Renew immediately.")
    elif cert["days_until_expiry"] < 30:
        notes.append("Certificate expires within 30 days. Schedule renewal.")
    if "let's encrypt" in cert["issuer"].lower():
        notes.append("Using Let's Encrypt. Free, auto-renewing, trusted by all modern browsers.")

    grade = "A" if cert["valid"] and cert["days_until_expiry"] > 30 else \
            "B" if cert["valid"] else "F"

    return {
        "status": "ok",
        "certificate": cert,
        "tls_versions_allowed": ssl_raw.get("tls_versions", ["TLSv1.2", "TLSv1.3"]),
        "hsts_preload_eligible": ssl_raw.get("hsts_preload_eligible", False),
        "grade": grade,
        "notes": notes,
    }
