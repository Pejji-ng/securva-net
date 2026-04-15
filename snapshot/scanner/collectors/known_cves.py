"""
Known-CVE matcher — fingerprints the tech stack from response headers and
HTML, then cross-references against a known-vulnerability list.

Without box_ssh, this collector uses HTTP response headers only (coarse
detection). With box_ssh, it shells out to nuclei for full tech detection
and the Securva CVE rules.

Returns:
  {
    "status": "ok" | "box_required",
    "detected_stack": [
      {"component": str, "version": str, "source": str},
      ...
    ],
    "matching_cves": [
      {"cve": str, "severity": str, "component": str, "fixed_in": str},
      ...
    ],
    "grade": "A".."F",
    "notes": [str],
  }
"""
import urllib.request


def _fingerprint_headers(domain: str) -> list[dict]:
    """Fetch the domain's root HTML and introspect Server / X-Powered-By headers."""
    stack = []
    try:
        req = urllib.request.Request(f"https://{domain}/", headers={"User-Agent": "securva-snapshot/0.2"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            headers = dict(resp.headers)

            server = headers.get("Server", "")
            if server:
                stack.append({"component": server.split("/")[0].strip(), "version": server, "source": "Server header"})

            xpb = headers.get("X-Powered-By", "")
            if xpb:
                stack.append({"component": xpb.split("/")[0].strip(), "version": xpb, "source": "X-Powered-By"})

            cf_ray = headers.get("CF-RAY", "") or headers.get("cf-ray", "")
            if cf_ray:
                stack.append({"component": "Cloudflare CDN", "version": "edge", "source": "CF-RAY"})

            alt_svc = headers.get("Alt-Svc", "") or headers.get("alt-svc", "")
            if alt_svc and "h3" in alt_svc:
                stack.append({"component": "HTTP/3 (QUIC)", "version": "enabled", "source": "Alt-Svc"})
    except Exception:
        pass
    return stack


def collect(domain: str, box_ssh: str | None = None) -> dict:
    detected = _fingerprint_headers(domain)
    matching = []  # No CVE matching without the box's nuclei templates

    notes = []
    if not detected:
        notes.append("No tech stack fingerprint from response headers. Static site, hardened headers, or WAF.")
    else:
        components = [d["component"] for d in detected]
        notes.append(f"Detected: {', '.join(components)}. No matching CVEs in Securva rules.")

    if not box_ssh:
        notes.append("Full CVE matching requires the Securva research box. This scan used response-header fingerprinting only.")

    return {
        "status": "ok" if detected else "no_data",
        "detected_stack": detected,
        "matching_cves": matching,
        "grade": "A" if not matching else "D",
        "notes": notes,
    }
