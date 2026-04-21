#!/usr/bin/env python3
"""
Securva Snapshot — Render Pipeline (Phase 3)

End-to-end rendering: takes a domain, runs the orchestrator (Phase 2),
feeds the JSON into the Jinja2 template (template.html.j2), and produces
a PDF via WeasyPrint.

Usage:
  # Full pipeline: orchestrate + render
  python3 render.py --domain babakizo.com --output /tmp/report.pdf

  # Render from a pre-computed orchestrator JSON
  python3 render.py --json sample-output-babakizo-com.json --output /tmp/report.pdf

  # Render to HTML only (skip PDF) for debugging
  python3 render.py --domain babakizo.com --html-only /tmp/report.html
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SCANNER_DIR = Path(__file__).parent
TEMPLATE_DIR = SCANNER_DIR.parent / "pdf-template"
TEMPLATE_FILE = "template.html.j2"
STYLESHEET_FILE = TEMPLATE_DIR / "style.css"


def load_orchestrator_output(domain: str | None, json_path: str | None) -> dict:
    """Either run orchestrator.py for a domain, or load a pre-computed JSON file."""
    if json_path:
        return json.loads(Path(json_path).read_text())
    if domain:
        from orchestrator import orchestrate
        return orchestrate(domain)
    raise ValueError("Must provide either --domain or --json")


def _load_web2_findings(web2_jsonl: str | None) -> list[dict]:
    """Optional Web2 pattern-lab scanner output loader.

    If `web2_jsonl` is provided AND the file exists, parse the JSONL and return
    a list of finding dicts. Template's Section 9 renders only when this list
    is non-empty. Missing file or empty list → Section 9 renders as no-op.
    """
    if not web2_jsonl:
        return []
    try:
        path = Path(web2_jsonl)
        if not path.exists():
            return []
        findings = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    findings.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return findings
    except Exception:
        return []


def prepare_template_context(report: dict, web2_jsonl: str | None = None) -> dict:
    """
    Transform the orchestrator output into the context dict Jinja2 expects.
    Adds convenience fields (scan_date formatted, report_id, etc) that the
    template uses directly.

    v1.0 (2026-04-21): optional `web2_jsonl` argument attaches pattern-lab-web2
    scanner output under the `web2_findings` key, which drives Section 9 of
    the template (Sector Peer Benchmarks). When absent or empty, Section 9
    renders as no-op via `{% if web2_findings %}` guard.
    """
    generated = report.get("generated_at_utc", "")
    try:
        scan_date = datetime.strptime(generated, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except Exception:
        scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "domain": report.get("domain", "unknown.com"),
        "report_id": report.get("report_id", "SEC-SS-UNKNOWN"),
        "scan_date": scan_date,
        "sections": report.get("sections", {}),
        "tier": report.get("tier", "Starter (NGN 30,000)"),
        "web2_findings": _load_web2_findings(web2_jsonl),
    }


def render_html(context: dict) -> str:
    """Render the Jinja2 template to HTML."""
    try:
        import jinja2
    except ImportError:
        print("ERROR: jinja2 not installed. Run: pip install jinja2", file=sys.stderr)
        sys.exit(2)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=jinja2.select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(TEMPLATE_FILE)
    return template.render(**context)


def render_pdf(html: str, output_path: str) -> None:
    """Render HTML to PDF via WeasyPrint using the shared stylesheet."""
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        print("ERROR: weasyprint not installed. Run: pip install weasyprint", file=sys.stderr)
        sys.exit(2)

    HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(
        output_path,
        stylesheets=[CSS(filename=str(STYLESHEET_FILE))],
    )


def main():
    parser = argparse.ArgumentParser(description="Securva Snapshot — render PDF from domain or JSON")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--domain", help="Target domain (runs orchestrator first)")
    src.add_argument("--json", help="Pre-computed orchestrator JSON file")
    parser.add_argument("--output", help="Output PDF path")
    parser.add_argument("--html-only", help="Render HTML only to this path, skip PDF generation")
    parser.add_argument("--web2-jsonl", dest="web2_jsonl",
                        help="Optional: pattern-lab-web2 scanner output JSONL. "
                             "When provided, Section 9 (Sector Peer Benchmarks) renders.")
    args = parser.parse_args()

    print("[+] loading orchestrator output...", file=sys.stderr)
    report = load_orchestrator_output(args.domain, args.json)

    print("[+] preparing template context...", file=sys.stderr)
    context = prepare_template_context(report, web2_jsonl=args.web2_jsonl)
    if context.get("web2_findings"):
        print(f"[+] web2_findings attached: {len(context['web2_findings'])}", file=sys.stderr)

    print(f"[+] rendering HTML for {context['domain']} ({context['report_id']})...", file=sys.stderr)
    html = render_html(context)

    if args.html_only:
        Path(args.html_only).write_text(html)
        print(f"[+] wrote HTML to {args.html_only} ({len(html)} chars)", file=sys.stderr)
        return

    if not args.output:
        parser.error("--output is required unless --html-only is used")

    print(f"[+] rendering PDF to {args.output}...", file=sys.stderr)
    render_pdf(html, args.output)
    size = Path(args.output).stat().st_size
    print(f"[+] done. PDF size: {size} bytes ({size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
