"""
Collector modules for the Securva Snapshot scanner orchestrator.

Each collector exposes `collect(domain, box_ssh=None) -> dict` matching a
well-defined shape that maps 1:1 to a section of the PDF template.

Collectors that require Securva-box-only tooling (subfinder, dnsx, nuclei,
github-dork-runner) accept a `box_ssh` parameter and either:
  1. Shell out to `ssh <box_ssh> <command>` when provided, OR
  2. Return a stub structure with `status=box_required` when not provided.

The orchestrator consumes all collector outputs and assembles the final JSON
report blob.
"""
from . import (
    executive_summary,
    security_headers,
    ssl_tls,
    ndpa_compliance,
    infrastructure,
    known_cves,
    code_exposure,
    remediation,
)

__all__ = [
    "executive_summary",
    "security_headers",
    "ssl_tls",
    "ndpa_compliance",
    "infrastructure",
    "known_cves",
    "code_exposure",
    "remediation",
]
