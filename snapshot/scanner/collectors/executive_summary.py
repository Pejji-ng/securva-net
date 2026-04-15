"""
Executive summary derivator — takes all other section outputs and produces
a top-level summary with overall grade, count of findings per severity, and
plain-English headline findings.

Output shape:
  {
    "overall_grade": "A".."F",
    "overall_score": int (0-100),
    "headline_findings": [str],  # 3 plain-English bullets
    "findings_by_severity": {"critical": int, "high": int, "medium": int, "low": int},
    "what_this_means": str,  # 1-paragraph impact statement
    "three_recommended_actions": [str],  # top 3 from remediation
  }
"""

GRADE_TO_SCORE = {"A": 10, "B": 8, "C": 6, "D": 4, "F": 0}


def _section_grade(sections: dict, key: str, default: str = "F") -> str:
    return sections.get(key, {}).get("grade", default)


def _headline(sections: dict) -> list[str]:
    headlines = []

    sh_grade = _section_grade(sections, "security_headers")
    passing = sum(1 for h in sections.get("security_headers", {}).get("headers", []) if h.get("status") == "pass")
    total = len(sections.get("security_headers", {}).get("headers", []))
    if total:
        headlines.append(f"Security headers: {passing}/{total} passing, grade {sh_grade}")

    ssl = sections.get("ssl_tls", {})
    cert = ssl.get("certificate", {})
    if cert.get("valid"):
        days = cert.get("days_until_expiry", 0)
        issuer = cert.get("issuer", "unknown")
        headlines.append(f"SSL certificate valid from {issuer}, expires in {days} days")
    else:
        headlines.append("SSL certificate INVALID or missing — critical")

    ndpa = sections.get("ndpa_compliance", {})
    if ndpa.get("cookie_consent") and ndpa.get("privacy_policy") and ndpa.get("ndpa_reference"):
        headlines.append("NDPA compliance signals all present")
    else:
        missing = []
        if not ndpa.get("cookie_consent"):
            missing.append("cookie consent")
        if not ndpa.get("privacy_policy"):
            missing.append("privacy policy")
        if not ndpa.get("ndpa_reference"):
            missing.append("NDPA reference")
        if missing:
            headlines.append(f"NDPA gaps: {', '.join(missing)}")

    code = sections.get("code_exposure", {})
    density = code.get("density_score", 0)
    if density >= 5:
        headlines.append(f"🚨 Public GitHub repo leaks credentials for {density}+ service integrations")
    elif code.get("findings"):
        headlines.append(f"Public GitHub exposure: {len(code['findings'])} findings")

    return headlines[:3]


def derive(domain: str, sections: dict) -> dict:
    # Overall grade: weighted average across the 5 core sections, rounded to letter.
    # Weights reflect business impact: headers/SSL/NDPA matter most, infra/CVE secondary.
    weights = {
        "security_headers": 25,
        "ssl_tls": 20,
        "ndpa_compliance": 25,
        "infrastructure": 15,
        "known_cves": 15,
    }
    total_weight = sum(weights.values())
    weighted_score = 0
    for section, weight in weights.items():
        g = _section_grade(sections, section)
        weighted_score += GRADE_TO_SCORE.get(g, 0) * weight
    overall_score = round(weighted_score / total_weight)

    # Score → letter grade
    if overall_score >= 9:
        overall = "A"
    elif overall_score >= 8:
        overall = "B"
    elif overall_score >= 6:
        overall = "C"
    elif overall_score >= 4:
        overall = "D"
    else:
        overall = "F"

    remediation = sections.get("remediation", {})
    high = remediation.get("priority_high", [])
    medium = remediation.get("priority_medium", [])
    low = remediation.get("priority_low", [])

    findings_by_sev = {
        "critical": sum(1 for f in high if "Rotate" in f.get("item", "") or "Patch" in f.get("item", "")),
        "high": len(high),
        "medium": len(medium),
        "low": len(low),
    }

    # 3 recommended actions: pull top-priority first, fall through to medium, then low
    pool = high + medium + low
    recommended = [t.get("item", "") for t in pool[:3]]

    # Plain-English "what this means"
    if overall == "A":
        what = f"{domain} passes every check in the Securva Snapshot. No critical issues detected. Maintain current hygiene practices and consider continuous monitoring."
    elif overall in ("B", "C"):
        what = f"{domain} has {len(high)} high-priority issue(s) and {len(medium)} medium-priority issue(s). These should be addressed within the next 30 days to bring the site to a clean baseline."
    else:
        what = f"{domain} has {len(high)} high-priority issue(s) that should be fixed this week. The overall grade reflects real risk to users and to business data."

    return {
        "overall_grade": overall,
        "overall_score": overall_score,
        "headline_findings": _headline(sections),
        "findings_by_severity": findings_by_sev,
        "what_this_means": what,
        "three_recommended_actions": recommended,
    }
