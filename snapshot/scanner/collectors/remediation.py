"""
Remediation roadmap builder — derivative collector. Consumes all other section
outputs and produces a grouped list of action items with estimated fix cost
(in-house hours OR Pejji package pricing in naira).

Output shape:
  {
    "priority_high": [{"item": str, "effort": str, "pejji_tier": str | None}],
    "priority_medium": [...],
    "priority_low": [...],
    "pejji_recommendation": str | None,
    "estimated_fix_hours_in_house": int,
  }
"""

PEJJI_TIERS = {
    "card": {"name": "Card", "price_ngn": 60000, "price_usd": 40, "covers": "quick-win header/SSL fixes for static sites"},
    "starter": {"name": "Starter", "price_ngn": 150000, "price_usd": 100, "covers": "landing page rebuild with security headers + NDPA + SSL"},
    "growth": {"name": "Growth", "price_ngn": 300000, "price_usd": 200, "covers": "multi-page business site with monitoring + booking"},
    "pro": {"name": "Pro", "price_ngn": 800000, "price_usd": 550, "covers": "e-commerce rebuild with Stripe/Paystack"},
    "pro_max": {"name": "Pro Max", "price_ngn": 1500000, "price_usd": 1000, "covers": "custom app with AI agent + ongoing security monitoring"},
}


def derive(sections: dict) -> dict:
    high = []
    medium = []
    low = []
    hours = 0

    # Security headers: each failing header is a fix
    sh = sections.get("security_headers", {})
    for h in sh.get("headers", []):
        if h.get("status") == "fail":
            high.append({
                "item": f"Add {h['name'].upper()} header",
                "effort": "30 min per environment",
                "pejji_tier": "card",
            })
            hours += 1

    # SSL
    ssl = sections.get("ssl_tls", {})
    cert = ssl.get("certificate", {})
    if cert.get("days_until_expiry", 999) < 14:
        high.append({
            "item": "Renew SSL certificate immediately",
            "effort": "15 min",
            "pejji_tier": "card",
        })
        hours += 1

    # NDPA
    ndpa = sections.get("ndpa_compliance", {})
    if not ndpa.get("cookie_consent", True):
        medium.append({
            "item": "Add cookie consent banner",
            "effort": "2 hours",
            "pejji_tier": "starter",
        })
        hours += 2
    if not ndpa.get("privacy_policy", True):
        high.append({
            "item": "Publish NDPA-aware privacy policy page",
            "effort": "3 hours (template + customization)",
            "pejji_tier": "starter",
        })
        hours += 3
    if ndpa.get("dpo_contact") == "missing":
        medium.append({
            "item": "Add Data Protection Officer contact to privacy policy",
            "effort": "15 min",
            "pejji_tier": None,
        })

    # Infrastructure DNS hygiene
    infra = sections.get("infrastructure", {})
    hygiene = infra.get("dns_hygiene", {})
    if hygiene.get("spf") != "pass":
        medium.append({"item": "Add SPF DNS record", "effort": "15 min", "pejji_tier": None})
    if hygiene.get("dmarc") != "pass":
        medium.append({"item": "Add DMARC DNS record", "effort": "30 min", "pejji_tier": None})
    if hygiene.get("caa") != "pass":
        low.append({"item": "Add CAA DNS record", "effort": "15 min", "pejji_tier": None})
    if hygiene.get("dnssec") != "pass":
        low.append({"item": "Enable DNSSEC at registrar", "effort": "1 hour", "pejji_tier": None})

    # CVE
    cves = sections.get("known_cves", {})
    for cve in cves.get("matching_cves", []):
        high.append({
            "item": f"Patch {cve['component']} for {cve['cve']}",
            "effort": "1-4 hours",
            "pejji_tier": "growth",
        })
        hours += 2

    # Code exposure
    code = sections.get("code_exposure", {})
    if code.get("density_score", 0) >= 5:
        high.append({
            "item": "Rotate all exposed credentials from public GitHub repo",
            "effort": "4-8 hours (per-provider rotation + git history purge)",
            "pejji_tier": "pro",
        })
        hours += 6

    # Pejji recommendation based on volume
    total = len(high) + len(medium) + len(low)
    if total == 0:
        recommendation = None
    elif len(high) == 0 and len(medium) <= 3:
        recommendation = PEJJI_TIERS["card"]
    elif len(high) >= 5 or len(cves.get("matching_cves", [])) > 0:
        recommendation = PEJJI_TIERS["growth"]
    elif total < 8:
        recommendation = PEJJI_TIERS["starter"]
    else:
        recommendation = PEJJI_TIERS["growth"]

    return {
        "priority_high": high,
        "priority_medium": medium,
        "priority_low": low,
        "estimated_fix_hours_in_house": hours,
        "pejji_recommendation": recommendation,
    }
