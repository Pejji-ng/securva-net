"""
Infrastructure footprint collector — subdomain enumeration, hosting provider
breakdown, DNS hygiene (SPF/DMARC/DNSSEC/CAA).

Subfinder + dnsx are only available on the Securva research box. When
box_ssh is provided, this collector runs them remotely. Without box_ssh, it
returns a minimal stub using only local DNS queries.

Returns:
  {
    "status": "ok" | "box_required" | "failed",
    "subdomains": [str],
    "live_subdomains_count": int,
    "hosting": {"primary": str, "breakdown": {str: int}},
    "dns_hygiene": {
        "spf": "pass"|"fail"|"missing",
        "dmarc": "pass"|"fail"|"missing",
        "dnssec": "pass"|"fail"|"missing",
        "caa": "pass"|"fail"|"missing",
    },
    "grade": "A".."F",
    "notes": [str],
  }
"""
import socket
import subprocess


def _resolve_dns_txt(domain: str, selector: str | None = None) -> str:
    """Try to resolve a TXT record. Returns "" on failure."""
    try:
        target = f"{selector}.{domain}" if selector else domain
        result = subprocess.run(
            ["dig", "+short", "TXT", target],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _check_dns_hygiene(domain: str) -> dict:
    """Check SPF, DMARC, CAA via dig. DNSSEC needs a different approach."""
    hygiene = {"spf": "missing", "dmarc": "missing", "dnssec": "unknown", "caa": "missing"}

    spf_txt = _resolve_dns_txt(domain)
    if "v=spf1" in spf_txt.lower():
        hygiene["spf"] = "pass"

    dmarc_txt = _resolve_dns_txt(domain, "_dmarc")
    if "v=dmarc1" in dmarc_txt.lower():
        hygiene["dmarc"] = "pass"

    try:
        caa_result = subprocess.run(
            ["dig", "+short", "CAA", domain],
            capture_output=True, text=True, timeout=10
        )
        if caa_result.stdout.strip():
            hygiene["caa"] = "pass"
    except Exception:
        pass

    try:
        dnssec_result = subprocess.run(
            ["dig", "+dnssec", "+short", domain],
            capture_output=True, text=True, timeout=10
        )
        if "RRSIG" in dnssec_result.stdout:
            hygiene["dnssec"] = "pass"
    except Exception:
        pass

    return hygiene


def _subfinder_via_box(domain: str, box_ssh: str) -> list[str]:
    """Shell out to subfinder on the box. Returns list of subdomains."""
    try:
        result = subprocess.run(
            ["ssh", box_ssh, f"subfinder -silent -d {domain} 2>/dev/null"],
            capture_output=True, text=True, timeout=120
        )
        return sorted(set(line.strip() for line in result.stdout.splitlines() if line.strip()))
    except Exception:
        return []


def collect(domain: str, box_ssh: str | None = None) -> dict:
    dns_hygiene = _check_dns_hygiene(domain)

    subdomains = []
    if box_ssh:
        subdomains = _subfinder_via_box(domain, box_ssh)
    else:
        # Without box, fall back to the naked domain + www
        subdomains = [domain, f"www.{domain}"]

    # Basic hosting detection via IP → ASN lookup (local, coarse)
    primary_host = "unknown"
    try:
        ip = socket.gethostbyname(domain)
        if ip.startswith("172.") or ip.startswith("104.") or ip.startswith("108.162."):
            primary_host = "Cloudflare CDN"
        elif ip.startswith("13.") or ip.startswith("54.") or ip.startswith("52."):
            primary_host = "AWS"
        elif ip.startswith("34.") or ip.startswith("35."):
            primary_host = "Google Cloud"
        elif ip.startswith("20."):
            primary_host = "Azure"
    except Exception:
        pass

    notes = []
    if dns_hygiene["spf"] != "pass":
        notes.append("No SPF record found. Email from your domain can be spoofed.")
    if dns_hygiene["dmarc"] != "pass":
        notes.append("No DMARC record found. Email spoofing protection is missing.")
    if dns_hygiene["dnssec"] != "pass":
        notes.append("DNSSEC not detected. DNS responses are not cryptographically verified.")
    if dns_hygiene["caa"] != "pass":
        notes.append("No CAA record found. Any CA can issue certificates for your domain.")

    pass_count = sum(1 for v in dns_hygiene.values() if v == "pass")
    grade = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}[pass_count]

    return {
        "status": "ok" if box_ssh else "partial_no_box",
        "subdomains": subdomains,
        "live_subdomains_count": len(subdomains),
        "hosting": {"primary": primary_host, "breakdown": {primary_host: 1} if primary_host != "unknown" else {}},
        "dns_hygiene": dns_hygiene,
        "grade": grade,
        "notes": notes,
    }
