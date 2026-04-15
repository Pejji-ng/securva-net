#!/usr/bin/env python3
"""
Securva Snapshot — Scanner Orchestrator (Phase 2)

Takes a domain as input, runs all 8 report-section collectors in parallel where
possible, and emits a single structured JSON blob that the PDF template
(Phase 3, Jinja2) will consume.

The JSON schema maps 1:1 to the 8 sections in the report:
  1. executive_summary
  2. security_headers
  3. ssl_tls
  4. ndpa_compliance
  5. infrastructure
  6. known_cves
  7. code_exposure
  8. remediation

Each collector is in snapshot/scanner/collectors/<section>.py and returns a
dict matching a well-defined shape. Collectors that need tools only available
on the Securva research box (subfinder, dnsx, nuclei, github-dork-runner) can
return a `box_required` marker — the orchestrator runs those via SSH in a
follow-up pass.

Usage:
  python3 orchestrator.py --domain babakizo.com
  python3 orchestrator.py --domain babakizo.com --output ./sample-output.json
  python3 orchestrator.py --domain babakizo.com --box-ssh babakinzo@165.232.109.143
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collectors import (
    executive_summary,
    security_headers,
    ssl_tls,
    ndpa_compliance,
    infrastructure,
    known_cves,
    code_exposure,
    remediation,
)

SCHEMA_VERSION = "snapshot-report/v1"


def generate_report_id(domain: str, ts: datetime) -> str:
    """Generate a deterministic but unique report ID."""
    date_part = ts.strftime("%Y%m%d")
    seq = ts.strftime("%H%M")
    return f"SEC-SS-{date_part}-{seq}"


def orchestrate(domain: str, box_ssh: str | None = None) -> dict:
    """Run all collectors against the target domain. Returns the full report dict."""
    start = time.monotonic()
    ts = datetime.now(timezone.utc)
    report_id = generate_report_id(domain, ts)

    report = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "domain": domain,
        "generated_at_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "securva-snapshot-orchestrator/0.2",
        "box_ssh_used": bool(box_ssh),
    }

    print(f"[+] orchestrating snapshot for {domain} (report_id={report_id})", file=sys.stderr)

    sections = {
        "security_headers": security_headers,
        "ssl_tls": ssl_tls,
        "ndpa_compliance": ndpa_compliance,
        "infrastructure": infrastructure,
        "known_cves": known_cves,
        "code_exposure": code_exposure,
    }

    section_results = {}
    for name, module in sections.items():
        print(f"[+]   collecting {name}...", file=sys.stderr)
        try:
            section_results[name] = module.collect(domain, box_ssh=box_ssh)
        except Exception as e:
            print(f"[!]   {name} failed: {e}", file=sys.stderr)
            section_results[name] = {"collection_error": str(e), "status": "failed"}

    # remediation + exec summary are derivative — they consume the other sections
    print("[+]   deriving remediation roadmap...", file=sys.stderr)
    section_results["remediation"] = remediation.derive(section_results)

    print("[+]   deriving executive summary...", file=sys.stderr)
    section_results["executive_summary"] = executive_summary.derive(domain, section_results)

    report["sections"] = section_results
    report["orchestration_seconds"] = round(time.monotonic() - start, 2)

    print(f"[+] done in {report['orchestration_seconds']}s", file=sys.stderr)
    return report


def main():
    parser = argparse.ArgumentParser(description="Securva Snapshot scanner orchestrator")
    parser.add_argument("--domain", required=True, help="Target domain (e.g., babakizo.com)")
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    parser.add_argument(
        "--box-ssh",
        help="SSH target for box-required collectors (e.g., babakinzo@165.232.109.143). "
             "Without this, box-required sections return stubs.",
    )
    args = parser.parse_args()

    report = orchestrate(args.domain, box_ssh=args.box_ssh)
    output_json = json.dumps(report, indent=2)

    if args.output:
        Path(args.output).write_text(output_json + "\n")
        print(f"[+] wrote {args.output} ({len(output_json)} bytes)", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
