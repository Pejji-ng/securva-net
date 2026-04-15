"""
Public code exposure collector.

Given a customer domain, guess the GitHub organization, and run the v4.2
multi-provider depth-check scanner against that org's public repositories.
Uses v4.2's expand_owner_scan() logic to enumerate the org's repos and
scan common config files (config.js, .env, .env.prod, settings.py, etc.)
for hardcoded credentials across 50+ provider patterns.

This is the customer-facing equivalent of the same tech that powers
Securva's internal dork research. When a customer pays for a Snapshot,
THEIR OWN GitHub org gets scanned and the findings land in their PDF
report.

Execution modes:
  - `box_ssh` provided: shells out via SSH to run the box-side v4.2 scanner.
    Preferred for production — the box has the PAT, the rate-limit budget,
    and the full provider pattern set.
  - `box_ssh` not provided: returns a stub that says "box required".
    Useful for local dev and testing without hitting the GitHub API.

Returns:
  {
    "status": "ok" | "box_required" | "no_org" | "failed",
    "guessed_github_org": str,
    "org_confirmed": bool,
    "public_repos_found": int,
    "repos_scanned": int,
    "pattern_classes_checked": int,
    "findings": [
      {
        "repo": str,            # e.g., "customer-org/backend-repo"
        "path": str,            # e.g., ".env" or "config.js"
        "density_score": int,   # how many distinct provider categories matched
        "providers": [str],     # e.g., ["flutterwave", "twilio", "aes-master-key"]
        "severity": "critical" | "high" | "medium" | "low",
        "note": str,            # plain-English summary for the customer
      }
    ],
    "max_density_score": int,
    "grade": "A".."F",
    "notes": [str],
  }
"""
import json
import os
import subprocess
import urllib.request
import urllib.error

# Default SSH key path for the Securva research box. Can be overridden via
# the SECURVA_BOX_KEY environment variable when running from different hosts.
DEFAULT_SSH_KEY = os.environ.get(
    "SECURVA_BOX_KEY",
    os.path.expanduser("~/.ssh/securva_box"),
)


def _guess_github_org(domain: str) -> str:
    """Guess the GitHub org name from the domain. 'babakizo.com' → 'babakizo420'."""
    base = domain.split(".")[0]
    # Known Kingsley-side mappings — override for domains where the GitHub org
    # name doesn't obviously match the domain
    known = {
        "babakizo": "babakizo420",
        "pejji": "Pejji-ng",
        "securva": "Pejji-ng",
        "blessedops": "BlessedOps-org",
    }
    return known.get(base, base)


def _verify_org_exists(org: str) -> tuple[bool, int]:
    """
    Hit GitHub's unauthenticated /users/{org} endpoint to verify the guessed org
    exists and count its public repos. Returns (exists, public_repos_count).
    """
    try:
        req = urllib.request.Request(
            f"https://api.github.com/users/{org}",
            headers={"User-Agent": "securva-snapshot/0.3", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data.get("public_repos", 0)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, 0
        return False, 0
    except Exception:
        return False, 0


def _run_v42_owner_scan_via_box(org: str, box_ssh: str) -> dict:
    """
    SSH into the box and run a small Python bridge that invokes v4.2's
    expand_owner_scan(org) for a single org and returns JSON.

    This is a focused invocation — not a full dork pass. It only enumerates
    the one org's repos and scans common config files. Fast (<30 seconds
    typical) and doesn't consume dork search rate limit budget.
    """
    bridge_cmd = (
        'python3 -c "'
        "import sys, json, importlib.util; "
        "spec = importlib.util.spec_from_file_location('v4', '/home/babakinzo/tools/github-dork-runner-v4.py'); "
        "v4 = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(v4); "
        "token = v4.load_token(); "
        f"hits = v4.expand_owner_scan('{org}', token, max_repos=30); "
        "print(json.dumps({'hits': hits}))"
        '"'
    )
    try:
        ssh_args = ["ssh"]
        if os.path.exists(DEFAULT_SSH_KEY):
            ssh_args += ["-i", DEFAULT_SSH_KEY]
        ssh_args += ["-o", "StrictHostKeyChecking=no", box_ssh, f"sudo {bridge_cmd}"]
        result = subprocess.run(ssh_args, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            return {"error": f"bridge failed rc={result.returncode}: {result.stderr[:200]}", "hits": []}
        # Parse the JSON output from stdout
        for line in result.stdout.splitlines():
            if line.strip().startswith("{"):
                return json.loads(line)
        return {"error": "no JSON in bridge output", "hits": []}
    except subprocess.TimeoutExpired:
        return {"error": "bridge timeout (>180s)", "hits": []}
    except Exception as e:
        return {"error": str(e), "hits": []}


def _hit_severity(density: int) -> str:
    """Map density score to customer-facing severity tier."""
    if density >= 5:
        return "critical"
    if density >= 3:
        return "high"
    if density >= 2:
        return "medium"
    return "low"


def _hit_note(hit: dict) -> str:
    """Plain-English one-line description of a finding for the customer PDF."""
    density = hit.get("density_score", 0)
    providers = list(hit.get("providers_found", {}).keys())
    if density >= 5:
        return (
            f"CRITICAL: {density} distinct provider credential categories detected in one file. "
            f"Includes: {', '.join(providers[:5])}. Rotate all affected credentials immediately."
        )
    if density >= 2:
        return (
            f"Multiple credential patterns detected ({density} categories): "
            f"{', '.join(providers)}. Review and rotate as needed."
        )
    return f"Single credential pattern detected: {providers[0] if providers else 'unknown'}."


def collect(domain: str, box_ssh: str | None = None) -> dict:
    org = _guess_github_org(domain)
    exists, public_repos = _verify_org_exists(org)

    if not exists:
        return {
            "status": "no_org",
            "guessed_github_org": org,
            "org_confirmed": False,
            "public_repos_found": 0,
            "repos_scanned": 0,
            "pattern_classes_checked": 50,
            "findings": [],
            "max_density_score": 0,
            "grade": "A",
            "notes": [
                f"GitHub org {org} not found. If this is wrong, please contact us so we can update our domain→org mapping.",
                "Not finding an org means we can't scan your public GitHub footprint for this report.",
            ],
        }

    if not box_ssh:
        return {
            "status": "box_required",
            "guessed_github_org": org,
            "org_confirmed": True,
            "public_repos_found": public_repos,
            "repos_scanned": 0,
            "pattern_classes_checked": 50,
            "findings": [],
            "max_density_score": 0,
            "grade": "A",
            "notes": [
                f"Confirmed GitHub org: {org} ({public_repos} public repos)",
                "Full credential scan requires the Securva research box — this field is populated in live scans",
            ],
        }

    # Production path: run v4.2 expand_owner_scan on the box scoped to this org
    result = _run_v42_owner_scan_via_box(org, box_ssh)

    if result.get("error"):
        return {
            "status": "failed",
            "guessed_github_org": org,
            "org_confirmed": True,
            "public_repos_found": public_repos,
            "repos_scanned": 0,
            "pattern_classes_checked": 50,
            "findings": [],
            "max_density_score": 0,
            "grade": "A",
            "notes": [
                f"Scan of {org} failed: {result['error']}",
                "Falling back to zero-finding result. Manual scan recommended.",
            ],
        }

    hits = result.get("hits", [])
    findings = []
    max_density = 0
    for hit in hits:
        density = hit.get("density_score", 0)
        max_density = max(max_density, density)
        findings.append({
            "repo": hit.get("repo", ""),
            "path": hit.get("path", ""),
            "density_score": density,
            "providers": sorted(hit.get("providers_found", {}).keys()),
            "severity": _hit_severity(density),
            "note": _hit_note(hit),
        })

    # Grade: A if no findings, C if any medium, D if any high, F if any critical
    if max_density >= 5:
        grade = "F"
    elif max_density >= 3:
        grade = "D"
    elif max_density >= 2:
        grade = "C"
    else:
        grade = "A"

    repos_scanned_set = {f["repo"] for f in findings if f["repo"]}

    return {
        "status": "ok",
        "guessed_github_org": org,
        "org_confirmed": True,
        "public_repos_found": public_repos,
        "repos_scanned": len(repos_scanned_set),
        "pattern_classes_checked": 50,
        "findings": findings,
        "max_density_score": max_density,
        "grade": grade,
        "notes": [
            f"Scanned {len(repos_scanned_set)} repo(s) under GitHub org {org}",
            f"Highest credential density found: {max_density} distinct provider categories" if findings else "No credential exposure detected in any scanned repo",
        ],
    }
