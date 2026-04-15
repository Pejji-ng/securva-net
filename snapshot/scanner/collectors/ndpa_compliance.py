"""
NDPA compliance collector — reuses api.securva.net/api/scan's ndpa block when
present. Checks:
  - Cookie consent banner present
  - Privacy policy page exists and reachable
  - Privacy policy references NDPA / NDPC
  - Contact email for data subject requests visible
  - Cross-border data transfer disclosure

Returns:
  {
    "status": "ok" | "failed",
    "cookie_consent": bool,
    "privacy_policy": bool,
    "ndpa_reference": bool,
    "dpo_contact": "unknown" | "found" | "missing",
    "data_subject_rights_documented": "unknown" | "found" | "missing",
    "cross_border_disclosure": "unknown" | "found" | "missing",
    "grade": "A".."F",
    "notes": [str],
  }
"""
import json
import urllib.request

API_URL = "https://api.securva.net/api/scan"
TIMEOUT = 30


def _fetch_api(domain: str) -> dict:
    url = f"{API_URL}?domain={domain}"
    req = urllib.request.Request(url, headers={"User-Agent": "securva-snapshot/0.2"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def collect(domain: str, box_ssh: str | None = None) -> dict:
    try:
        raw = _fetch_api(domain)
    except Exception as e:
        return {"status": "failed", "error": str(e), "grade": "F"}

    ndpa_raw = raw.get("ndpa", {}) or {}

    cookie = bool(ndpa_raw.get("cookie_consent", False))
    pp = bool(ndpa_raw.get("privacy_policy", False))
    ndpa_ref = bool(ndpa_raw.get("ndpa_reference", False))

    # Fields not in current api.securva.net but in the Snapshot spec
    dpo_contact = ndpa_raw.get("dpo_contact", "unknown")
    dsr = ndpa_raw.get("data_subject_rights", "unknown")
    cross_border = ndpa_raw.get("cross_border_disclosure", "unknown")

    # Grading: 3 core signals (cookie, privacy policy, NDPA reference) are required.
    # If all 3 pass → A. 2/3 → B. 1/3 → D. 0/3 → F.
    core_pass = sum([cookie, pp, ndpa_ref])
    grade_map = {3: "A", 2: "B", 1: "D", 0: "F"}
    grade = grade_map[core_pass]

    notes = []
    if not cookie:
        notes.append("No cookie consent banner detected. NDPA Art. 26 requires explicit consent for non-essential cookies.")
    if not pp:
        notes.append("No privacy policy page detected at expected URLs. NDPA Art. 24 requires a publicly accessible privacy notice.")
    if not ndpa_ref and pp:
        notes.append("Privacy policy does not reference NDPA / NDPC. Consider adding the regulatory reference for clarity.")
    if dpo_contact == "missing":
        notes.append("No Data Protection Officer contact email visible. Required if you process Nigerian user data at scale.")
    if cross_border == "missing":
        notes.append("No cross-border data transfer disclosure. If you use non-Nigerian cloud infrastructure, this must be disclosed per NDPA Art. 41.")

    return {
        "status": "ok",
        "cookie_consent": cookie,
        "privacy_policy": pp,
        "ndpa_reference": ndpa_ref,
        "dpo_contact": dpo_contact,
        "data_subject_rights_documented": dsr,
        "cross_border_disclosure": cross_border,
        "grade": grade,
        "notes": notes,
    }
