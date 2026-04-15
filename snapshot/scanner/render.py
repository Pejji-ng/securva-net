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


def prepare_template_context(report: dict) -> dict:
    """
    Transform the orchestrator output into the context dict Jinja2 expects.
    Adds convenience fields (scan_date formatted, report_id, etc) that the
    template uses directly.
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
    args = parser.parse_args()

    print("[+] loading orchestrator output...", file=sys.stderr)
    report = load_orchestrator_output(args.domain, args.json)

    print("[+] preparing template context...", file=sys.stderr)
    context = prepare_template_context(report)

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
